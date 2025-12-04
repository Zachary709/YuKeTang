"""
答案文件解析模块。

用于解析 answer/ 目录下的 txt 文件，提取每章每题的答案。
答案格式：用 **答案内容** 包裹。
"""

import os
import re
from typing import Dict, List, Optional, Tuple


def _calculate_text_similarity(text1: str, text2: str) -> float:
    """
    计算两段文本的字符重叠度（Jaccard 相似度）。

    用于验证当前题目与答案文件中对应题目是否匹配。
    允许个别字符不同或顺序错开，只要大部分字符相同即可。

    Args:
        text1: 第一段文本
        text2: 第二段文本

    Returns:
        相似度分数，范围 0.0 ~ 1.0
    """
    if not text1 or not text2:
        return 0.0

    # 移除空白字符、标点和常见无意义内容，只保留有意义的字符
    clean1 = re.sub(r'[\s\[\]填空\d，。、：:？?！!""''（）()．.·]', '', text1)
    clean2 = re.sub(r'[\s\[\]填空\d，。、：:？?！!""''（）()．.·]', '', text2)

    if not clean1 or not clean2:
        return 0.0

    # 使用字符集合计算 Jaccard 相似度
    set1 = set(clean1)
    set2 = set(clean2)

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    return intersection / union


def parse_answer_file(file_path: str) -> Dict[str, Dict[int, dict]]:
    """
    解析答案文件，返回按章节和题号组织的答案字典。

    文件格式示例：
        ## 第一章-AI安全与伦理概述
        1. AI 解释生成系统的手段包括：**注意力网络**、**解耦表征**、**生成解释**
        2. 面向数据隐私的攻击方式有：**成员推断攻击** 和 **模型反演攻击**

    返回格式：
        {
            "第一章": {
                1: {"text": "AI 解释生成系统的手段包括：...", "answers": ["注意力网络", "解耦表征", "生成解释"]},
                2: {"text": "面向数据隐私的攻击方式有：...", "answers": ["成员推断攻击", "模型反演攻击"]},
            },
            ...
        }

    Args:
        file_path: 答案文件的绝对路径

    Returns:
        嵌套字典：外层 key 为章节名（如 "第一章"），内层 key 为题号（int），
        value 为包含 "text"（题目文本）和 "answers"（答案列表）的字典
    """
    if not os.path.exists(file_path):
        return {}

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result: Dict[str, Dict[int, dict]] = {}
    current_chapter: str = ""

    # 正则匹配章节标题，如 "## 第一章-AI安全与伦理概述" 或 "## 第四章-后门攻击与防御"
    chapter_pattern = re.compile(r'^##\s*(第.+?章)', re.MULTILINE)
    # 正则匹配题目行，如 "1. AI 解释生成系统的手段包括：**注意力网络**..."
    question_pattern = re.compile(r'^(\d+)\.\s*(.+)$', re.MULTILINE)
    # 正则匹配 **答案** 格式
    answer_pattern = re.compile(r'\*\*([^*]+)\*\*')

    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检查是否是章节标题
        chapter_match = chapter_pattern.match(line)
        if chapter_match:
            current_chapter = chapter_match.group(1)  # 如 "第一章"
            if current_chapter not in result:
                result[current_chapter] = {}
            continue

        # 检查是否是题目行
        question_match = question_pattern.match(line)
        if question_match and current_chapter:

            question_num = int(question_match.group(1))
            question_content = question_match.group(2)

            

            # 提取所有 **答案**
            answers = answer_pattern.findall(question_content)

            # 移除答案标记后的题目文本（用于相似度验证）
            clean_text = re.sub(r'\*\*[^*]+\*\*', '', question_content).strip()

            if answers:
                # if current_chapter == "第四章":
                #     print(question_num)
                #     print(question_content)
                result[current_chapter][question_num] = {
                    "text": clean_text,
                    "answers": answers,
                }
    return result


def get_answer_for_question(
    parsed_answers: Dict[str, Dict[int, dict]],
    chapter_name: str,
    question_index: int,
    course_name: str = "",
) -> Optional[dict]:
    """
    根据章节名和题号获取答案数据。

    Args:
        parsed_answers: parse_answer_file 返回的解析结果
        chapter_name: 章节名，如 "第一章-AI安全与伦理概述" 或 "第一章 AI安全与伦理概述"
        question_index: 题目在当前测试中的索引（从0开始，会自动 +1 匹配题号）
        course_name: 课程名称，用于特殊处理（如"人工智能安全与伦理"第4章20/21题是多选题）

    Returns:
        包含 "text" 和 "answers" 的字典；若未找到返回 None
    """
    # 从 chapter_name 中提取 "第X章" 部分
    chapter_key_match = re.search(r'(第.+?章)', chapter_name)
    if not chapter_key_match:
        return None

    chapter_key = chapter_key_match.group(1)  # 如 "第一章"
    question_num = question_index + 1  # 索引从0开始，题号从1开始

    chapter_data = parsed_answers.get(chapter_key)
    if not chapter_data:
        return None

    return chapter_data.get(question_num)


def verify_answer_match(
    stored_text: str,
    current_text: str,
    similarity_threshold: float = 0.7,
) -> Tuple[bool, float]:
    """
    验证本地答案文件中的题目文本与当前题目是否匹配。

    用于防止因题目顺序变化或题目文本略有差异导致答案错配。
    允许个别字符不同或顺序错开，只要大部分字符相同即可。

    Args:
        stored_text: 答案文件中存储的题目文本
        current_text: 当前正在处理的题目文本
        similarity_threshold: 相似度阈值，默认 0.7

    Returns:
        元组 (是否匹配, 相似度分数)
    """
    stored_text = stored_text.replace("&nbsp;", "")
    current_text = current_text.replace("&nbsp;", "")
    similarity = _calculate_text_similarity(stored_text, current_text)
    return (similarity >= similarity_threshold, similarity)


def format_answer_for_submission(answers: List[str]) -> List[str]:
    """
    将解析出的答案格式化为可提交的格式（仅用于填空题）。

    Args:
        answers: 解析出的答案列表

    Returns:
        答案列表
    """
    if not answers:
        return []
    return answers


def match_answers_to_options(
    local_answers: List[str],
    options: List[dict],
    is_multiple_choice: bool = False,
) -> List[str]:
    """
    将本地答案文本与选项进行匹配，返回匹配的选项字母。

    对于单选题：返回与答案相似度最高的一个选项
    对于多选题：返回与每个答案相似度最高的选项列表

    Args:
        local_answers: 本地答案文本列表
        options: 选项列表，每个元素为 {"key": "A", "value": "选项内容"}
        is_multiple_choice: 是否为多选题

    Returns:
        匹配的选项字母列表，如 ["A"] 或 ["A", "B", "C"]
    """
    if not local_answers or not options:
        return []

    matched_keys = []

    if is_multiple_choice:
        # 多选题：为每个本地答案找到最匹配的选项
        for ans in local_answers:
            best_key = None
            best_similarity = 0.0
            for opt in options:
                similarity = _calculate_text_similarity(ans, opt.get("value", ""))
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_key = opt.get("key")
            if best_key and best_key not in matched_keys:
                matched_keys.append(best_key)
    else:
        # 单选题：找到与所有答案组合后相似度最高的单个选项
        combined_answer = "".join(local_answers)
        best_key = None
        best_similarity = 0.0
        for opt in options:
            similarity = _calculate_text_similarity(combined_answer, opt.get("value", ""))
            if similarity > best_similarity:
                best_similarity = similarity
                best_key = opt.get("key")
        if best_key:
            matched_keys = [best_key]

    return matched_keys


def load_course_answers(course_name: str, answer_dir: Optional[str] = None) -> Dict[str, Dict[int, dict]]:
    """
    加载指定课程的答案文件。

    Args:
        course_name: 课程名称，如 "人工智能安全与伦理"
        answer_dir: 答案目录路径，默认为项目根目录下的 answer/

    Returns:
        解析后的答案字典，若文件不存在则返回空字典
    """
    if answer_dir is None:
        # 获取项目根目录（假设此文件在 src/utils/ 下）
        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        answer_dir = os.path.join(project_root, "answer")

    # 构建答案文件路径
    answer_file = os.path.join(answer_dir, f"{course_name}.txt")

    if not os.path.exists(answer_file):
        return {}

    return parse_answer_file(answer_file)


def has_local_answers(course_name: str, answer_dir: Optional[str] = None) -> bool:
    """
    检查是否存在指定课程的本地答案文件。

    Args:
        course_name: 课程名称
        answer_dir: 答案目录路径

    Returns:
        True 如果答案文件存在，否则 False
    """
    if answer_dir is None:
        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        answer_dir = os.path.join(project_root, "answer")

    answer_file = os.path.join(answer_dir, f"{course_name}.txt")
    return os.path.exists(answer_file)
