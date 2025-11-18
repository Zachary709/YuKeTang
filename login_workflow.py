import asyncio
import json
import os
import webbrowser

import websockets

from http_client import session
from logging_utils import log_error, log_info


async def run_websocket_login():
    """使用 WebSocket 登录，生成并扫描二维码。"""
    uri = "wss://www.yuketang.cn/wsapp"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Mobile Safari/537.36',
        'Origin': "https://www.yuketang.cn",
    }
    data = {
        "op": "requestlogin",
        "role": "web",
        "version": 1.4,
        "type": "qrcode",
        "from": "web"
    }

    async with websockets.connect(uri, extra_headers=headers) as websocket:
        json_data = json.dumps(data)
        await websocket.send(json_data)

        while True:
            response = await websocket.recv()

            if 'ticket' in response:
                response_json = json.loads(response)
                url = response_json['ticket']

                img_response = session.get(url=url)
                if img_response.status_code == 200:
                    with open('login_qr.png', 'wb') as file:
                        file.write(img_response.content)

                    log_info("请微信扫码登录！")
                    webbrowser.open('file://' + os.path.realpath('login_qr.png'))
                else:
                    log_error(f"二维码获取失败，状态码：{img_response.status_code}")

            if 'subscribe_status' in response:
                json_data = json.loads(response)
                auth = json_data['Auth']
                user_id = json_data['UserID']

                url = "https://www.yuketang.cn/pc/web_login"
                payload = json.dumps({"UserID": user_id, "Auth": auth})
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko'
                }
                session.post(url, data=payload, headers=headers)
                break

    return


def run_login_flow():
    """同步封装，便于主流程调用。"""
    asyncio.run(run_websocket_login())

