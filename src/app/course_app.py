from src.utils.logging_utils import log_error, log_info
from src.auth.cookies_manager import are_cookies_valid, load_cookies
from src.auth.login_workflow import run_websocket_login
from src.core.course_progress import run_course_session
import asyncio


def main():
    # 1. 尝试加载本地 cookies
    load_cookies()

    # 2. 校验 cookies 是否仍然有效；无效则触发扫码登录
    if not are_cookies_valid():
        log_info("开始扫码登录流程...")
        asyncio.run(run_websocket_login())

    while True:
        try:
            run_course_session()
        except Exception as exc:
            log_error(f"刷课过程中出现异常：{exc}")
        choice = input("是否继续刷下一门课程？(y/n)：").strip().lower()
        if choice not in ('y', 'yes', '1'):
            log_info("已结束刷课，再见！")
            break


if __name__ == '__main__':
    main()


