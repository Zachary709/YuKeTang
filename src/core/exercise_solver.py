"""
测试题自动答题模块。

支持单选题、多选题、判断题和填空题。
"""

import json
import os
import re
import time
import random
from io import BytesIO
from typing import Any

from src.network.http_client import SEPARATOR, session
from src.utils.logging_utils import log_error, log_info, log_success, log_warning
from src.core.course_progress import (
    _select_course,
    _get_csrf_token,
    _extract_sku_id_from_logs,
    _get_score_detail,
)
from src.llm import solve_problem_with_llm
from src.utils.font_decode_utils import (
    decode_encrypted_spans,
    strip_html_tags,
    load_or_build_font_map,
)
from src.utils.answer_parser import (
    load_course_answers,
    has_local_answers,
    get_answer_for_question,
    format_answer_for_submission,
    verify_answer_match,
    match_answers_to_options,
)


# ============== API 调用相关函数 ==============

def _get_course_chapter(classroom_id: str, university_id: int) -> dict:
    """
    获取课程章节信息，从中筛选 leaf_type=6 的测试题。
    """
    url = "https://www.yuketang.cn/mooc-api/v1/lms/learn/course/chapter"
    params = {
        "cid": classroom_id,
        "term": "latest",
        "uv_id": university_id,
        "classroom_id": classroom_id,
    }

    headers = {
        "accept": "application/json, text/plain, */*",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xtbz": "ykt",
        "x-client": "web",
    }
    csrf = _get_csrf_token()
    if csrf:
        headers["x-csrftoken"] = csrf

    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        return resp.json()
    except Exception as exc:
        log_warning(f"获取课程章节信息失败：{exc}")
        return {}


def _extract_exercise_leaf_ids(chapter_data: dict) -> list[dict]:
    """
    从章节数据中提取所有测试题的信息（leaf_type=6）。

    返回格式：[{"id": xxx, "name": xxx, "chapter_name": xxx}, ...]
    """
    exercise_leaves = []
    chapters = chapter_data.get("data", {}).get("course_chapter", [])

    for chapter in chapters:
        chapter_name = chapter.get("name", "未知章节")
        section_leaf_list = chapter.get("section_leaf_list", [])

        for sec in section_leaf_list:
            # 检查 section 本身是否为测试题
            if sec.get("leaf_type") == 6 and sec.get("id"):
                exercise_leaves.append({
                    "id": sec["id"],
                    "name": sec.get("name", "未知测试题"),
                    "chapter_name": chapter_name,
                })

            # 检查 leaf_list 中的测试题
            leaf_list = sec.get("leaf_list", [])
            if isinstance(leaf_list, list):
                for leaf in leaf_list:
                    if leaf.get("leaf_type") == 6 and leaf.get("id"):
                        exercise_leaves.append({
                            "id": leaf["id"],
                            "name": leaf.get("name", "未知测试题"),
                            "chapter_name": chapter_name,
                        })

    return exercise_leaves


def _get_leaf_info(classroom_id: str, leaf_id: int, university_id: int) -> dict | None:
    """
    获取测试题的 leaf_info，从中提取 leaf_type_id。

    API: /mooc-api/v1/lms/learn/leaf_info/{classroom_id}/{leaf_id}/
    """
    url = f"https://www.yuketang.cn/mooc-api/v1/lms/learn/leaf_info/{classroom_id}/{leaf_id}/"
    headers = {
        "accept": "application/json, text/plain, */*",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xt-agent": "web",
        "xtbz": "ykt",
    }

    try:
        resp = session.get(url, headers=headers, timeout=10)
        return resp.json()
    except Exception as exc:
        log_warning(f"获取 leaf_info 失败（leaf_id={leaf_id}）：{exc}")
        return None


def _get_exercise_list(leaf_type_id: int, classroom_id: str, university_id: int) -> dict | None:
    """
    获取测试题列表。

    API: /mooc-api/v1/lms/exercise/get_exercise_list/{leaf_type_id}/
    """
    url = f"https://www.yuketang.cn/mooc-api/v1/lms/exercise/get_exercise_list/{leaf_type_id}/"
    headers = {
        "accept": "application/json, text/plain, */*",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xt-agent": "web",
        "xtbz": "ykt",
    }

    try:
        resp = session.get(url, headers=headers, timeout=10)
        return resp.json()
    except Exception as exc:
        log_warning(f"获取测试题列表失败（leaf_type_id={leaf_type_id}）：{exc}")
        return None


# ============== 题目解析相关函数 ==============

def _parse_problem(problem: dict, font_map: dict[str, str]) -> dict:
    """
    解析单个题目，返回标准化格式。
    """
    content = problem.get("content", {})
    problem_id = content.get("ProblemID") or problem.get("problem_id")
    problem_type = content.get("Type", "")
    problem_type_text = content.get("TypeText", "")
    body = content.get("Body", "")
    options = content.get("Options", [])
    blanks = content.get("Blanks", [])
    score = content.get("Score", 0)
    index = problem.get("index", 0)

    # 解密题目内容
    decoded_body = decode_encrypted_spans(body, font_map)
    clean_body = strip_html_tags(decoded_body)

    # 解密选项
    decoded_options = []
    for opt in options:
        opt_value = opt.get("value", "")
        decoded_value = decode_encrypted_spans(opt_value, font_map)
        clean_value = strip_html_tags(decoded_value)
        decoded_options.append({
            "key": opt.get("key", ""),
            "value": clean_value,
        })

    return {
        "index": index,
        "problem_id": problem_id,
        "type": problem_type,
        "type_text": problem_type_text,
        "body": clean_body,
        "options": decoded_options,
        "blanks": blanks,
        "score": score,
    }


# ============== 提交答案相关函数 ==============

def _submit_answer(
    classroom_id: str,
    university_id: int,
    problem_id: int,
    answer: str | list[str],
    problem_type: str,
) -> bool:
    """
    提交单个题目的答案。

    API: /mooc-api/v1/lms/exercise/problem_apply/

    注意：填空题使用 "answers" 字段（字典格式），其他题型使用 "answer" 字段（数组格式）。
    """
    url = "https://www.yuketang.cn/mooc-api/v1/lms/exercise/problem_apply/"
    csrf_token = _get_csrf_token()

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xt-agent": "web",
        "xtbz": "ykt",
    }
    if csrf_token:
        headers["x-csrftoken"] = csrf_token

    # 根据题目类型构建答案格式和 payload
    if problem_type == "FillBlank":
        # 填空题答案格式：字典，key 从 "1" 开始，如 {"1": "答案1", "2": "答案2"}
        if isinstance(answer, list):
            answers_dict = {str(i + 1): ans for i, ans in enumerate(answer)}
        else:
            answers_dict = {"1": answer}
        payload = {
            "classroom_id": int(classroom_id),
            "problem_id": problem_id,
            "answers": answers_dict,
        }
    elif problem_type == "MultipleChoice":
        # 多选题答案格式：数组，如 ["A", "B", "C"]
        if isinstance(answer, str):
            answer_data = [a.strip() for a in answer.split(",")]
        else:
            answer_data = answer
        payload = {
            "classroom_id": int(classroom_id),
            "problem_id": problem_id,
            "answer": answer_data,
        }
    elif problem_type == "TrueFalse" or problem_type == "Judge":
        # 判断题答案格式：数组，如 ["true"] 或 ["false"]
        if isinstance(answer, list):
            answer_data = answer
        else:
            answer_data = [answer]
        payload = {
            "classroom_id": int(classroom_id),
            "problem_id": problem_id,
            "answer": answer_data,
        }
    else:
        # 单选题答案格式：数组，如 ["B"]
        if isinstance(answer, list):
            answer_data = answer
        else:
            answer_data = [answer]
        payload = {
            "classroom_id": int(classroom_id),
            "problem_id": problem_id,
            "answer": answer_data,
        }

    try:
        resp = session.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    except Exception as exc:
        log_error(f"提交答案失败（problem_id={problem_id}）：{exc}")
        return False

    try:
        data = resp.json()
    except Exception:
        data = None

    if resp.status_code == 200 and data and data.get("success"):
        log_success(f"答案提交成功：problem_id={problem_id}")
        return True

    log_warning(f"答案提交可能失败，状态码={resp.status_code}，响应={resp.text[:200]}")
    return False


# ============== 主函数 ==============

def run_exercise_solver_session():
    """
    自动刷当前课程的所有测试题（leaf_type=6）。

    步骤：
    1. 选择课程，得到 classroom_id / university_id；
    2. 获取课程章节信息，筛选测试题；
    3. 对每个测试题获取 leaf_info，提取 leaf_type_id；
    4. 获取题目列表，解密题目内容；
    5. 使用 LLM 解答题目；
    6. 提交答案。
    """
    # 1. 选择课程
    classroom_id, university_id, course_info = _select_course()
    course_name = course_info.get("name", "")
    log_info(f"当前选择课程：{course_name}（classroom_id={classroom_id}）")

    # 2. 获取课程章节信息
    log_info("正在获取课程章节信息...")
    chapter_data = _get_course_chapter(classroom_id, university_id)
    if not chapter_data:
        log_error("获取课程章节信息失败，无法继续。")
        return

    # 3. 筛选测试题
    exercise_leaves = _extract_exercise_leaf_ids(chapter_data)
    if not exercise_leaves:
        log_warning("未找到任何测试题（leaf_type=6）。")
        return

    # log_info(f"检测到 {len(exercise_leaves)} 个测试题。")
    # for i, ex in enumerate(exercise_leaves):
    #     log_info(f"  {i + 1}. {ex['chapter_name']} - {ex['name']}")

    log_info(SEPARATOR)

    # 让用户选择要刷的测试题，选择后立即检测分数并处理，处理完返回选择页
    font_map: dict[str, str] = {}
    all_answers = []  # 累计会话内所有答案

    # 检查是否存在本地答案文件
    local_answers = {}
    if has_local_answers(course_name):
        log_success(f"检测到本地答案文件：answer/{course_name}.txt，将优先使用本地答案。")
        local_answers = load_course_answers(course_name)
        # print(local_answers['第四章'])
        # return
    else:
        log_info("未检测到本地答案文件，将使用 LLM 生成答案。")

    while True:
        # 重新输出测试列表，方便选择
        log_info(f"检测到 {len(exercise_leaves)} 个测试题：")
        for i, ex in enumerate(exercise_leaves):
            log_info(f"  {i + 1}. {ex['chapter_name']} - {ex['name']}")
        log_info(SEPARATOR)
        user_input = input("请输入要刷的测试题编号（输入 0 刷全部，输入 -1 退出返回上一级）：\n")
        try:
            num = int(user_input)
        except ValueError:
            log_warning("输入错误，请确保您输入的是一个整数。")
            continue

        if num == -1:
            log_info("已退出测试题选择，返回上一级。")
            break

        if num == 0:
            selected_exercises = exercise_leaves
        elif 1 <= num <= len(exercise_leaves):
            selected_exercises = [exercise_leaves[num - 1]]
        else:
            log_warning(f"输入错误，请输入 0 到 {len(exercise_leaves)} 之间的编号，或 -1 退出。")
            continue

        # 在每次选择后检测哪些测试为未得分（user_score == 0），仅处理这些测试
        try:
            sku_id = _extract_sku_id_from_logs(classroom_id)
        except Exception:
            sku_id = None

        unscored_leaf_ids = set()
        if sku_id:
            try:
                score_detail = _get_score_detail(sku_id=sku_id, classroom_id=classroom_id, university_id=university_id)
                leaf_infos = score_detail.get('data', {}).get('leaf_level_infos', [])
                for item in leaf_infos:
                    if item.get('leaf_type') == 6 and item.get('id'):
                        try:
                            user_score_val = float(item.get('user_score', 0) or 0)
                        except (TypeError, ValueError):
                            user_score_val = 0.0
                        if user_score_val == 0.0:
                            unscored_leaf_ids.add(int(item.get('id')))
            except Exception as exc:
                log_warning(f"检测未得分测试时出现异常：{exc}，将继续但不会按分数过滤。")
        else:
            log_warning("未从学习日志中提取到 sku_id，无法按测试得分过滤；将处理用户选择的测试。")

        # 过滤 selected_exercises，只保留未得分（user_score==0）的测试（若有检测结果）
        if unscored_leaf_ids:
            before_cnt = len(selected_exercises)
            selected_exercises = [ex for ex in selected_exercises if int(ex.get('id') or 0) in unscored_leaf_ids]
            log_info(f"按分数过滤后，将处理 {len(selected_exercises)} 个未得分测试（原选择 {before_cnt} 个）。")

        if not selected_exercises:
            log_info("当前选择未包含任何未得分测试或已被过滤，返回选择。")
            continue

        # 本次选择的临时答案汇总
        batch_answers = []

        # 开始处理选中的测试
        for ex_idx, exercise in enumerate(selected_exercises, start=1):
            print(exercise)
            leaf_id = exercise["id"]
            exercise_name = exercise["name"]
            chapter_name = exercise["chapter_name"]

            log_info(SEPARATOR)
            log_info(f"正在处理第 {ex_idx}/{len(selected_exercises)} 个测试题：{chapter_name} - {exercise_name}")

            # 获取 leaf_info，提取 leaf_type_id
            leaf_info = _get_leaf_info(classroom_id, leaf_id, university_id)
            if not leaf_info or not leaf_info.get("success"):
                log_warning(f"获取 leaf_info 失败，跳过此测试题。")
                continue

            content_info = leaf_info.get("data", {}).get("content_info", {})
            leaf_type_id = content_info.get("leaf_type_id")
            if not leaf_type_id:
                log_warning(f"未找到 leaf_type_id，跳过此测试题。")
                continue

            log_info(f"已获取 leaf_type_id={leaf_type_id}")

            # 获取题目列表
            exercise_list = _get_exercise_list(leaf_type_id, classroom_id, university_id)
            if not exercise_list or not exercise_list.get("success"):
                log_warning(f"获取题目列表失败，跳过此测试题。")
                continue

            problems = exercise_list.get("data", {}).get("problems", [])
            if not problems:
                log_warning(f"未找到任何题目，跳过此测试题。")
                continue

            # 获取字体映射（如有）
            font_url = exercise_list.get("data", {}).get("font", "")
            if font_url:
                log_info(f"检测到字体混淆，正在解析字体映射...")
                try:
                    font_map = load_or_build_font_map(font_url)
                    log_success(f"字体映射解析完成，共 {len(font_map)} 个字符。")
                except Exception as exc:
                    log_warning(f"字体映射解析失败：{exc}，将尝试不解密继续。")

            log_info(f"共 {len(problems)} 道题目，开始答题...")

            # 遍历题目
            for prob_idx, problem in enumerate(problems, start=1):
                parsed_problem = _parse_problem(problem, font_map)

                log_info(SEPARATOR)
                log_info(f"第 {prob_idx}/{len(problems)} 题 ({parsed_problem['type_text']})：")
                log_info(f"  题目：{parsed_problem['body'][:100]}...")
                for opt in parsed_problem.get("options", []):
                    log_info(f"  {opt['key']}: {opt['value']}")

                # 检查是否已提交
                submission_status = problem.get("submission_status")
                if submission_status is not None:
                    log_info(f"  该题已提交过，跳过。")
                    continue

                # 优先尝试从本地答案文件获取答案
                answer = None
                answer_source = "LLM"

                # 对填空题和选择题使用本地答案
                problem_type = parsed_problem["type"]
                if local_answers and problem_type in ["FillBlank", "SingleChoice", "MultipleChoice"]:
                    # 使用 prob_idx（从 1 开始的连续编号）作为题号匹配答案
                    # 注意：get_answer_for_question 期望的是从 0 开始的索引，所以传入 prob_idx - 1
                    
                    answer_data = get_answer_for_question(
                        parsed_answers=local_answers,
                        chapter_name=chapter_name,
                        question_index=prob_idx - 1,
                        course_name=course_name,
                    )
                    if answer_data:
                        # 验证题目文本是否匹配（防止因题目包含图片等导致答案错配）
                        stored_text = answer_data.get("text", "")
                        is_match, similarity = verify_answer_match(stored_text, parsed_problem["body"])

                        if is_match:
                            local_answer_list = answer_data.get("answers", [])
                            
                            if problem_type == "FillBlank":
                                # 填空题：直接使用答案列表
                                answer = format_answer_for_submission(local_answer_list)
                            elif problem_type in ["SingleChoice", "MultipleChoice"]:
                                # 选择题：将答案与选项进行相似度匹配
                                is_multiple = (problem_type == "MultipleChoice")
                                answer = match_answers_to_options(
                                    local_answers=local_answer_list,
                                    options=parsed_problem.get("options", []),
                                    is_multiple_choice=is_multiple,
                                )
                                if not answer:
                                    log_warning(f"  本地答案无法匹配到选项，跳过本地答案。")
                                    answer = None
                            
                            if answer:
                                answer_source = "本地答案文件"
                                log_info(f"  从本地答案文件获取到答案（相似度{similarity:.2f}）：{answer}")
                        else:
                            log_warning(f"  本地答案文件第{prob_idx}题文本不匹配（相似度{similarity:.2f}），跳过本地答案。")

                # 如果本地没有答案，使用 LLM 生成
                if not answer:
                    answer = solve_problem_with_llm(parsed_problem, course_name, exercise_name)
                    if answer:
                        log_info(f"  LLM 生成答案：{answer}")

                if not answer:
                    log_warning(f"  未能获取答案（本地和 LLM 均失败），跳过此题。")
                    continue

                # 汇总答案
                entry = {
                    "chapter": chapter_name,
                    "exercise": exercise_name,
                    "index": parsed_problem["index"],
                    "type": parsed_problem["type_text"],
                    "body": parsed_problem["body"],
                    "answer": answer,
                    "source": answer_source,
                }
                batch_answers.append(entry)
                all_answers.append(entry)

                # 如果是本地答案，直接提交（包括填空题）
                if answer_source == "本地答案文件":
                    log_info(f"  使用本地答案提交...")
                    success = _submit_answer(
                        classroom_id=classroom_id,
                        university_id=university_id,
                        problem_id=parsed_problem["problem_id"],
                        answer=answer,
                        problem_type=parsed_problem["type"],
                    )
                    delay = random.uniform(3, 5)
                    log_info(f"  等待 {delay:.1f} 秒后继续下一题")
                    time.sleep(delay)
                    if not success:
                        log_warning(f"  答案提交失败。")
                    continue

                # LLM 答案：填空题不自动提交，仅供参考
                if parsed_problem["type"] == "FillBlank":
                    log_info("  [LLM 填空题答案仅供参考，请手动填写]")
                    continue

                # LLM 答案：其他题型自动提交
                success = _submit_answer(
                    classroom_id=classroom_id,
                    university_id=university_id,
                    problem_id=parsed_problem["problem_id"],
                    answer=answer,
                    problem_type=parsed_problem["type"],
                )
                delay = random.uniform(3, 5)
                log_info(f"  等待 {delay:.1f} 秒后继续下一题")
                time.sleep(delay)
                if not success:
                    log_warning(f"  答案提交失败。")
                

            log_success(f"测试题 '{exercise_name}' 处理完成！")

        # 本次选择结束，展示本批次的答题汇总，便于复制粘贴
        if batch_answers:
            print("\n================= 本次答案汇总（仅供参考） =================\n")
            for item in batch_answers:
                print(f"[{item['chapter']} - {item['exercise']}] 第{item['index']}题（{item['type']}）：")
                print(f"题目：{item['body']}")
                print(f"答案：{item['answer']}\n")
            print("================= 复制以上内容填写 =================\n")
        else:
            log_info("本次没有生成任何答案。")

        # 新增：每次刷完后询问是否继续
        cont = input("是否继续刷测试题？输入 y 继续，其他任意键返回上一级：\n")
        if cont.strip().lower() != 'y':
            log_info("已选择返回上一级。"); break

    # 退出选择循环后，展示会话内累计的所有答案（如有）
    # if all_answers:
    #     print("\n================= 本次会话累计答案汇总（仅供参考） =================\n")
    #     for item in all_answers:
    #         print(f"[{item['chapter']} - {item['exercise']}] 第{item['index'] + 1}题（{item['type']}）：")
    #         print(f"题目：{item['body']}")
    #         print(f"答案：{item['answer']}\n")
    #     print("================= 复制以上内容填写 =================\n")
