import json
import os

from src.network.http_client import session
from src.utils.logging_utils import log_error, log_info


COOKIE_FILE = "cookies.json"


def save_cookies():
    """将当前 session 的 cookies 保存到本地文件。"""
    try:
        cookies_dict = {c.name: c.value for c in session.cookies}
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies_dict, f, ensure_ascii=False, indent=2)
        log_info("已保存登录 cookies。")
    except Exception as exc:
        log_error(f"保存 cookies 失败：{exc}")


def load_cookies():
    """从本地文件加载 cookies 到 session，如果文件不存在则静默跳过。"""
    if not os.path.exists(COOKIE_FILE):
        return
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            cookies_dict = json.load(f)
        for name, value in cookies_dict.items():
            session.cookies.set(name, value, domain="www.yuketang.cn", path="/")
        log_info("已从本地加载 cookies。")
    except Exception as exc:
        log_error(f"加载 cookies 失败：{exc}")


def are_cookies_valid():
    """
    调用一个需要登录的接口，判断当前 cookies 是否仍然有效。
    这里使用课程列表接口作为校验依据。
    """
    import requests  # noqa: F401  # 保留以兼容原逻辑

    url = "https://www.yuketang.cn/v2/api/web/courses/list?identity=2"
    try:
        resp = session.get(url, timeout=10)
    except Exception as exc:
        log_error(f"检测 cookies 有效性时网络异常：{exc}")
        return False

    if resp.status_code != 200:
        log_error(f"检测 cookies 有效性失败，状态码：{resp.status_code}")
        return False

    try:
        data = resp.json()
    except Exception:
        log_error("检测 cookies 有效性失败，响应非 JSON。")
        return False

    # 简单判断：如果能正常拿到课程列表 data.list，就认为登录有效
    course_list = data.get("data", {}).get("list")
    if isinstance(course_list, list) and len(course_list) > 0:
        log_info("检测到已有有效登录状态，将复用本地 cookies。")
        return True

    log_info("当前 cookies 已失效或未登录，需要重新扫码登录。")
    return False


