"""
字体混淆解码相关工具函数。
"""
import re
from io import BytesIO
import os
import json
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

def decode_encrypted_spans(html_text: str, char_map: dict | None = None) -> str:
    """
    解码类似：
    <span class="xuetangx-com-encrypted-font">\u793e\u95f4</span>\u6d51...
    中 span 包裹部分的文本，并用 char_map 做字符映射。
    """
    if char_map is None:
        char_map = {}
    pattern = re.compile(
        r'<span\s+class="xuetangx-com-encrypted-font"\s*>(.*?)</span>'
    )
    def _decode_inner(m):
        raw = m.group(1)
        res = ''
        for c in raw:
            res += char_map.get(c, c)
        return res
    return pattern.sub(_decode_inner, html_text)

def strip_html_tags(html: str) -> str:
    """移除 HTML 标签，只保留文本内容。"""
    html = re.sub(r"</p\s*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<.*?>", "", html)
    return text.strip()

def font_to_img_ddddocr(code_list: list[str], filename: str) -> dict[str, str]:
    """
    使用 ddddocr 识别字体中的字符映射。
    """
    try:
        import ddddocr
    except ImportError:
        return {}
    normal_dict = {}
    ocr = ddddocr.DdddOcr(show_ad=False)
    for char_code in code_list:
        real_char = char_code.encode('utf-8').decode('utf-8')
        img_size = 1024
        img = Image.new('1', (img_size, img_size), 255)
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(filename, int(img_size * 0.7))
        bbox = draw.textbbox((0, 0), real_char, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        draw.text(
            ((img_size - text_width) // 2, (img_size - text_height) // 2),
            real_char,
            font=font,
            fill=0,
        )
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='JPEG')
        img_bytes = img_byte_arr.getvalue()
        res = ocr.classification(img_bytes)
        if res:
            normal_dict[real_char] = res
    return normal_dict

def ttf_parse(url: str, ttf_name: str) -> dict[str, str]:
    """
    根据 URL 获取字体文件并解析字符映射。
    """
    import requests
    response = requests.get(url, proxies={"http": None, "https": None})
    font_parse = TTFont(BytesIO(response.content))
    font_parse.save(ttf_name)
    m_dict = font_parse.getBestCmap()
    unicode_list = list(m_dict.keys())
    char_list = [chr(ch_unicode) for ch_unicode in unicode_list]
    normal_dict = font_to_img_ddddocr(char_list, ttf_name)
    if os.path.exists(ttf_name):
        os.remove(ttf_name)
    return normal_dict

def load_or_build_font_map(url: str) -> dict[str, str]:
    """
    读取/构建字体映射关系：
    - 缓存文件名基于 font URL 生成，确保不同字体使用不同缓存
    - 缓存文件保存在 font_cache 子目录下
    - 若本地已存在 JSON 缓存文件，则直接读取；
    - 否则调用 ttf_parse 重新计算，并写入缓存。
    """
    import hashlib
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "font_cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    font_filename = url.split("/")[-1]
    cache_name = font_filename.replace(".ttf", ".json").replace(".woff", ".json").replace(".woff2", ".json")
    if not cache_name.endswith(".json"):
        cache_name = hashlib.md5(url.encode()).hexdigest() + ".json"
    cache_path = os.path.join(cache_dir, cache_name)
    ttf_name = os.path.join(cache_dir, "temp_font.ttf")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "normal_dict" in data:
            return data["normal_dict"]
        return data
    normal_dict = ttf_parse(url, ttf_name)
    cache_data = {"normal_dict": normal_dict, "font_url": url}
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    return normal_dict
