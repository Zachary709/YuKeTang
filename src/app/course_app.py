from src.utils.logging_utils import log_error, log_info
from src.auth.cookies_manager import are_cookies_valid, load_cookies
from src.auth.login_workflow import run_websocket_login
from src.core.course_progress import run_course_session, run_discussion_comment_session
import asyncio


def _ensure_login():
    """确保当前 session 处于登录状态，必要时触发扫码登录。"""
    load_cookies()

    if not are_cookies_valid():
        log_info("开始扫码登录流程...")
        asyncio.run(run_websocket_login())


def main():
    _ensure_login()

    while True:
        print("请选择功能：")
        print("1. 自动刷视频")
        print("2. 自动刷讨论题评论")
        print("0. 退出")
        choice = input("请输入功能编号：").strip()

        if choice == "1":
            try:
                run_course_session()
            except Exception as exc:
                log_error(f"刷视频过程中出现异常：{exc}")
        elif choice == "2":
            try:
                run_discussion_comment_session()
            except Exception as exc:
                log_error(f"刷讨论题评论过程中出现异常：{exc}")
        elif choice == "0":
            log_info("已退出程序，再见！")
            break
        else:
            log_info("输入有误，请重新选择。")


if __name__ == '__main__':
    main()


