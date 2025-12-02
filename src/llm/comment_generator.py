import re

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


def _extract_tag_content(text: str, tag: str = "topic_text") -> str | None:
    """
    从文本中提取指定标签包裹的内容，例如 <topic_text>xxx</topic_text>。
    """
    pattern = rf"<{tag}>(.*?)</{tag}>"
    m = re.search(pattern, text, flags=re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


def _get_openai_client() -> OpenAI | None:
    api_key = get_dashscope_api_key()
    if not api_key:
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


def generate_comment_by_llm(question_html: str, course_name: str | None = None) -> str | None:
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


