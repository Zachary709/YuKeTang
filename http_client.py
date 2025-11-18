import random
import time

import requests

random.seed(int(time.time()))

session = requests.Session()
session.trust_env = False

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.70 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
]

REFERERS = [
    'https://www.yuketang.cn/v2/web/index',
]

SESSION_USER_AGENT = random.choice(USER_AGENTS)
SESSION_REFERER = random.choice(REFERERS)
SEPARATOR = '-' * 45

__all__ = [
    "session",
    "SESSION_USER_AGENT",
    "SESSION_REFERER",
    "SEPARATOR",
]

