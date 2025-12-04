import asyncio
import json
import os
import threading
import tkinter as tk
import webbrowser

import websockets

from src.network.http_client import session
from src.utils.logging_utils import log_error, log_info
from src.auth.cookies_manager import save_cookies


_qr_window = None


def _show_qr_window(image_path: str):
    """在独立窗口中展示二维码图片。

    优先使用 Pillow 以兼容更多图片格式；如果 Pillow 不可用或加载失败，
    自动回退到使用系统默认图片查看器打开（但此时将无法自动关闭）。
    """
    global _qr_window
    root = None
    try:
        from PIL import Image, ImageTk  # type: ignore

        root = tk.Tk()
        root.title("雨课堂扫码登录")

        img = Image.open(image_path)
        photo = ImageTk.PhotoImage(img)

        label = tk.Label(root, image=photo)
        # 防止被垃圾回收
        label.image = photo # type: ignore
        label.pack(padx=10, pady=10)

        _qr_window = root
        root.mainloop()
    except ImportError:
        # 未安装 Pillow，回退到系统图片查看器
        log_error("未安装 Pillow 库，无法以自定义窗口显示二维码，将改用系统默认图片查看器。"
                  "如需自动关闭二维码窗口，请先执行：pip install pillow")
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        webbrowser.open('file://' + os.path.realpath(image_path))
    except Exception as exc:
        log_error(f"显示二维码窗口失败：{exc}，将改用系统默认图片查看器。")
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        webbrowser.open('file://' + os.path.realpath(image_path))


def open_qr_window(image_path: str):
    """在后台线程中启动二维码窗口，不阻塞主逻辑。"""
    thread = threading.Thread(target=_show_qr_window, args=(image_path,), daemon=True)
    thread.start()


def close_qr_window():
    """关闭已打开的二维码窗口（如果存在）。"""
    global _qr_window
    if _qr_window is not None:
        try:
            _qr_window.after(0, _qr_window.destroy)
        except Exception:
            # 即便关闭失败也不影响后续逻辑
            pass
        finally:
            _qr_window = None


async def run_websocket_login():
    """使用 WebSocket 登录，生成并扫描二维码。"""
    uri = "wss://www.yuketang.cn/wsapp"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/94.0.4606.71 Mobile Safari/537.36',
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

            if 'ticket' in response: # type: ignore
                response_json = json.loads(response)
                url = response_json['ticket']

                img_response = session.get(url=url)
                if img_response.status_code == 200:
                    with open('login_qr.png', 'wb') as file:
                        file.write(img_response.content)

                    log_info("请使用微信扫码登录（已弹出二维码窗口）！")
                    # 打开自定义二维码窗口，便于扫码完成后自动关闭
                    open_qr_window(os.path.realpath('login_qr.png'))
                else:
                    log_error(f"二维码获取失败，状态码：{img_response.status_code}")

            if 'subscribe_status' in response: # type: ignore
                json_data = json.loads(response)
                auth = json_data['Auth']
                user_id = json_data['UserID']

                url = "https://www.yuketang.cn/pc/web_login"
                payload = json.dumps({"UserID": user_id, "Auth": auth})
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; '
                                  'Trident/7.0; rv:11.0) like Gecko'
                }
                resp = session.post(url, data=payload, headers=headers)
                if resp.status_code == 200:
                    log_info("扫码登录成功，正在保存 cookies。")
                    save_cookies()
                    # 扫码完成后自动关闭二维码窗口
                    close_qr_window()
                else:
                    log_error(f"扫码登录失败，状态码：{resp.status_code}")
                break

    return


def run_login_flow():
    """同步封装，便于主流程调用。"""
    asyncio.run(run_websocket_login())


