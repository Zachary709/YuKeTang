"""
保持向后兼容的入口脚本。

实际业务逻辑已迁移到 src.app.course_app.main。
"""

from src.app.course_app import main


if __name__ == '__main__':
    main()

