import time


def log(message, level="INFO"):
    """统一输出格式"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{timestamp}] [{level.upper()}] {message}")


def log_info(message):
    log(message, "INFO")


def log_warning(message):
    log(message, "WARN")


def log_error(message):
    log(message, "ERROR")


def log_success(message):
    log(message, "SUCCESS")


