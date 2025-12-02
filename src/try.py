import imp
from pdb import run
import requests
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# # 1. 配置接口地址
# url = "https://xidianyjs.yuketang.cn/v/discussion/v2/comment/?term=latest&uv_id=2924"

# # 2. 配置 Headers
# # 注意：你需要把下面的 '你的Cookie字符串' 替换为你在浏览器F12里看到的真实Cookie
# headers = {
#     "accept": "application/json, text/plain, */*",
#     "content-type": "application/json",
#     "platform-id": "3",
#     "university-id": "2924",
#     "x-client": "web",
#     "x-csrftoken": "GpbANKSoPrSnGPmk2DWswjeIVGdb2ulA", # 这里要换成你抓包到的最新token
#     "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
#     "cookie": "KYT0tnMlOCSxlE8yy0Jv5IVFsTstxSjV" 
# }

# # 3. 配置评论内容
# payload = {
#     "to_user": 87942275,   # 保持抓包到的ID，或者你要回复的人的ID
#     "topic_id": 22695705,  # 话题ID
#     "content": {
#         "text": "这是通过Python脚本自动发送的测试评论！", # 你想发的内容
#         "upload_images": [],
#         "accessory_list": []
#     },
#     "anchor": 0
# }

# # 4. 发送请求
# try:
#     response = requests.post(url, headers=headers, data=json.dumps(payload))
    
#     # 5. 检查结果
#     if response.status_code == 200:
#         print("评论发送成功！")
#         print("服务器返回:", response.text)
#     else:
#         print(f"发送失败，状态码: {response.status_code}")
#         print("错误信息:", response.text)

# except Exception as e:
#     print("发生错误:", e)


from src.core.course_progress import run_course_session

run_course_session()