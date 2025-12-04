import re
from typing import List, Optional, Union

from openai import OpenAI

from src.utils.config_utils import (
    get_dashscope_api_key,
    get_llm_base_url,
    get_llm_model_name,
)
from src.utils.logging_utils import log_error, log_warning, log_info


def _strip_html_tags(html: str) -> str:
    """简单移除 HTML 标签，只保留文本内容。"""
    html = re.sub(r"</p\s*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<.*?>", "", html)
    return text.strip()


def _extract_tag_content(text: str, tag: str = "topic_text") -> Optional[str]:
    """
    从文本中提取指定标签包裹的内容，例如 <topic_text>xxx</topic_text>。
    """
    pattern = rf"<{tag}>(.*?)</{tag}>"
    m = re.search(pattern, text, flags=re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


def _get_openai_client() -> Optional[OpenAI]:
    api_key = get_dashscope_api_key()
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        log_error("未在 config.yml 中配置 DASHSCOPE_API_KEY，无法通过 LLM 生成评论。")
        return None
    try:
        base_url = get_llm_base_url()
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        return client
    except Exception as exc:
        log_error(f"初始化 OpenAI 客户端失败：{exc}")
        return None


def generate_comment_by_llm(question_html: str, course_name: Optional[str] = None) -> Optional[str]:
    """
    使用 LLM 根据讨论题目自动生成一小段评论内容。

    要求模型只输出形如：
      <topic_text>你的简短评论</topic_text>
    的内容，方便后续解析。
    """
    client = _get_openai_client()
    if client is None:
        return None

    question_text = _strip_html_tags(question_html or "")
    if not question_text:
        question_text = "这是一个关于某个研究生课程学习体会的讨论题。"

    log_info("问题：")
    log_info(question_text)

    system_prompt = (
        "你是一个积极乐观的研究生，需要在网课课程的评论区里根据问题留下评论。\n"
        "请根据给定的“课程名称”和“讨论题目内容”，用中文生成一段（6~8 句）自然的个人思考，避免空话套话。\n"
        "不要提及课程名称，会显得很生硬。核心观点也不要走极端，要积极乐观。\n"
        "严格按照下面格式输出：\n"
        "<topic_text>这里是你的完整回答内容</topic_text>\n"
        "不要输出任何多余说明、解释或其它标签。"
    )

    if course_name:
        user_prompt = f"课程名称：{course_name}\n讨论题目内容如下：\n{question_text}"
    else:
        user_prompt = f"讨论题目内容如下：\n{question_text}"

    model_name = get_llm_model_name()

    max_retry = 10
    for attempt in range(1, max_retry + 1):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
            )
        except Exception as exc:
            log_warning(f"调用 LLM 生成评论失败（第 {attempt} 次）：{exc}")
            continue

        content = completion.choices[0].message.content if completion.choices else ""
        if not content:
            log_warning(f"LLM 返回空内容（第 {attempt} 次），重试中……")
            continue

        extracted = _extract_tag_content(content, tag="topic_text")
        if extracted:
            log_info("回答：")
            log_info(extracted)
            return extracted

        log_warning(f"LLM 返回内容未包含 <topic_text> 标签（第 {attempt} 次），将重试。")

    log_error("多次尝试后仍未获取到合法格式的 LLM 评论内容，将放弃本次自动生成。")
    return None


# ============== 测试题答题相关函数 ==============

def _format_problem_for_llm(problem: dict, course_name: Optional[str] = None, exercise_name: Optional[str] = None) -> str:
    """
    将题目格式化为 LLM 提示词格式。
    """
    problem_type = problem.get("type", "")
    problem_type_text = problem.get("type_text", "")
    body = problem.get("body", "")
    options = problem.get("options", [])
    blanks = problem.get("blanks", [])

    lines = []
    if course_name:
        lines.append(f"课程名称：{course_name}")
    if exercise_name:
        lines.append(f"测试名称：{exercise_name}")
    lines.append(f"题目类型：{problem_type_text}")
    lines.append(f"题目内容：{body}")

    if options:
        lines.append("选项：")
        for opt in options:
            lines.append(f"  {opt['key']}: {opt['value']}")

    if blanks and problem_type == "FillBlank":
        lines.append(f"填空数量：{len(blanks)} 个空")

    return "\n".join(lines)


def _extract_answer_from_response(response_text: str, problem_type: str) -> Union[str, List[str], None]:
    """
    从 LLM 响应中提取答案。

    支持的格式：
    - 单选题/判断题：<answer>A</answer> 或 <answer>true</answer>
    - 多选题：<answer>A,B,C</answer>
    - 填空题：<answer>答案1|答案2|答案3</answer>
    """
    pattern = r"<answer>(.*?)</answer>"
    match = re.search(pattern, response_text, flags=re.DOTALL)

    if not match:
        return None

    answer = match.group(1).strip()

    if problem_type == "FillBlank":
        # 填空题返回列表
        return [a.strip() for a in answer.split("|")]
    elif problem_type == "MultipleChoice":
        # 多选题返回逗号分隔的选项
        return answer.replace(" ", "").upper()
    else:
        # 单选题/判断题返回单个答案
        return answer.strip()


def solve_problem_with_llm(problem: dict, course_name: Optional[str] = None, exercise_name: Optional[str] = None) -> Union[str, List[str], None]:
    """
    使用 LLM 解答单个题目。
    """
    client = _get_openai_client()
    if client is None:
        return None

    problem_type = problem.get("type", "")
    problem_text = _format_problem_for_llm(problem, course_name, exercise_name)

    # 根据题目类型构建不同的提示词
    if problem_type == "SingleChoice":
        system_prompt = (
            "你是一个答题助手。请仔细阅读题目和选项，选出正确答案。\n"
            "你必须严格按照以下格式输出答案：\n"
            "<answer>选项字母</answer>\n"
            "例如：<answer>A</answer>\n"
            "不要输出任何多余的解释或说明。"
        )
    elif problem_type == "MultipleChoice":
        system_prompt = (
            "你是一个答题助手。请仔细阅读题目和选项，选出所有正确答案。\n"
            "你必须严格按照以下格式输出答案（多个选项用逗号分隔）：\n"
            "<answer>A,B,C</answer>\n"
            "不要输出任何多余的解释或说明。"
        )
    elif problem_type == "TrueFalse" or problem_type == "Judge":
        system_prompt = (
            "你是一个答题助手。请判断题目描述是否正确。\n"
            "你必须严格按照以下格式输出答案：\n"
            "如果正确：<answer>true</answer>\n"
            "如果错误：<answer>false</answer>\n"
            "不要输出任何多余的解释或说明。"
        )
    elif problem_type == "FillBlank":
        blanks_count = len(problem.get("blanks", []))
        system_prompt = (
            f"你是一个答题助手。请仔细阅读题目，填写 {blanks_count} 个空的答案。\n"
            "你必须严格按照以下格式输出答案（多个答案用 | 分隔）：\n"
            "<answer>答案1|答案2|答案3</answer>\n"
            "不要输出任何多余的解释或说明。"
        )
    else:
        system_prompt = (
            "你是一个答题助手。请仔细阅读题目，给出正确答案。\n"
            "你必须严格按照以下格式输出答案：\n"
            "<answer>你的答案</answer>\n"
            "不要输出任何多余的解释或说明。"
        )

    model_name = get_llm_model_name()
    max_retry = 10

    for attempt in range(1, max_retry + 1):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": problem_text},
                ],
                stream=False,
            )
        except Exception as exc:
            log_warning(f"调用 LLM 答题失败（第 {attempt} 次）：{exc}")
            continue

        content = completion.choices[0].message.content if completion.choices else ""
        if not content:
            log_warning(f"LLM 返回空内容（第 {attempt} 次），重试中……")
            continue

        answer = _extract_answer_from_response(content, problem_type)
        if answer:
            return answer

        log_warning(f"LLM 返回内容未包含 <answer> 标签（第 {attempt} 次），将重试。")

    log_error("多次尝试后仍未获取到合法格式的 LLM 答案。")
    return None
