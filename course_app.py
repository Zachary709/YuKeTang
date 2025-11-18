from logging_utils import log_error, log_info
from login_workflow import run_login_flow
from course_progress import run_course_session


def main():
    run_login_flow()

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

