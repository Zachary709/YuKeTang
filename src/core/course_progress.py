import json
from pdb import run
import random
import time

from typing import Any, Dict, List, Optional, Tuple

from src.network.http_client import SEPARATOR, SESSION_REFERER, SESSION_USER_AGENT, session
from src.utils.logging_utils import log_error, log_info, log_success, log_warning
from src.utils.config_utils import get_default_comment
from src.llm import generate_comment_by_llm


def random_sleep_interval():
    """随机心跳睡眠，避免被判异常。"""
    base = random.uniform(0.3, 0.8)
    if random.random() < 0.1:
        base += random.uniform(0.5, 1.5)
    time.sleep(base)


def _select_course() -> Tuple[str, int, Dict]:
    """
    复用课程选择逻辑，返回 (classroom_id, university_id, course_info)。
    """
    url = 'https://www.yuketang.cn/v2/api/web/courses/list?identity=2'
    response = session.get(url=url)

    course_response = response.json()
    course_list = course_response.get('data', {}).get('list', [])

    if not course_list:
        log_warning("未检测到课程数据，请检查是否登录成功。")
        raise SystemExit(-1)

    if len(course_list) > 1:
        for i, course in enumerate(course_list):
            log_info(f"序号：{i} ----- {course['name']}")
        log_info(SEPARATOR)

        min_value = 0
        max_value = len(course_list) - 1

        while True:
            user_input = input("请输入需要操作的课程编号：\n")
            try:
                num = int(user_input)
                if min_value <= num <= max_value:
                    course_info = course_list[num]
                    classroom_id = str(course_info['classroom_id'])
                    university_id = int(course_info.get('course', {}).get('university_id', 0))
                    if not university_id:
                        log_warning("未获取到 university_id，后续部分接口可能会失败。")
                    return classroom_id, university_id, course_info
                log_warning(f"输入错误，请输入一个介于 {min_value} 和 {max_value} 之间的课程编号。")
            except ValueError:
                log_warning("输入错误，请确保您输入的是一个整数。")
    else:
        course_info = course_list[0]
        classroom_id = str(course_info['classroom_id'])
        university_id = int(course_info.get('course', {}).get('university_id', 0))
        if not university_id:
            log_warning("未获取到 university_id，后续部分接口可能会失败。")
        return classroom_id, university_id, course_info


def run_course_session():
    """选择课程并持续刷课（视频）。"""
    classroom_id, university_id, course_info = _select_course()

    url = (
        "https://www.yuketang.cn/v2/api/web/logs/learn/"
        f"{classroom_id}?actype=-1&page=0&offset=20&sort=-1"
    )
    response = session.get(url)
    course_logs = response.json()

    activities = course_logs['data'].get('activities', [])
    target_activity = None

    if len(activities) > 1 and activities[1].get('courseware_id'):
        target_activity = activities[1]
    else:
        for activity in activities:
            courseware_id = activity.get('courseware_id')
            if courseware_id:
                target_activity = activity
                break

    if not target_activity:
        log_warning("选中课程暂无可刷视频，自动跳过。")
        return

    url = (
        'https://www.yuketang.cn/c27/online_courseware/xty/kls/pub_news/'
        f"{target_activity['courseware_id']}/"
    )
    headers = {
        'xtbz': 'ykt',
        'classroom-id': str(classroom_id)
    }
    response = session.get(url, headers=headers)

    courseware_detail = response.json()
    c_course_id = str(courseware_detail['data']['course_id'])
    s_id = str(courseware_detail['data']['s_id'])

    def extract_video_leafs(chapter):
        section_list = chapter.get('section_list', [])
        videos = []
        if section_list:
            for section in section_list:
                leafs = section.get('leaf_list', [])
                if not leafs:
                    continue
                for leaf in leafs:
                    if leaf.get('leaf_type') == 0 and leaf.get('id'):
                        videos.append(leaf)
        else:
            for leaf in chapter.get('leaf_list', []):
                if leaf.get('leaf_type') == 0 and leaf.get('id'):
                    videos.append(leaf)
        return videos

    # 备用：通过章节接口一次性获取每章视频 leaf（避免某些结构下只拿到测试题）
    fallback_chapter_videos = _get_course_chapter_videos(
        classroom_id=classroom_id,
        university_id=university_id,
    )

    for i, chapter in enumerate(courseware_detail['data']['content_info']):
        # 1. 先从原有 content_info 结构中提取视频
        primary_videos = extract_video_leafs(chapter)

        # 2. 再从章节接口补充同一章节的视频，做并集（按 id 去重）
        extra_videos = []
        if fallback_chapter_videos and i < len(fallback_chapter_videos):
            extra_videos = fallback_chapter_videos[i] or []

        if extra_videos:
            # 构建去重集合
            seen_ids = {str(v["id"]) for v in primary_videos if v.get("id")}
            merged = list(primary_videos)
            added_count = 0
            for v in extra_videos:
                vid = v.get("id")
                if vid is None:
                    continue
                vid_str = str(vid)
                if vid_str not in seen_ids:
                    merged.append({"id": vid})
                    seen_ids.add(vid_str)
                    added_count += 1
            # if added_count > 0:
            #     log_info(
            #         f"通过章节接口在第{i + 1}章额外补充发现 {added_count} 个视频，将一并刷取。"
            #     )
            video_leafs = merged
        else:
            video_leafs = primary_videos
        log_info(
            f"正在观看----{courseware_detail['data']['c_short_name']} 第{i + 1}章----共找到{len(video_leafs)}个视频。"
        )
        if not video_leafs:
            log_warning("该章节未找到可刷视频，自动跳过。")
            continue

        for j, leaf in enumerate(video_leafs):
            cards_id = '0'
            video_id = str(leaf['id'])

            url = (
                'https://www.yuketang.cn/mooc-api/v1/lms/learn/leaf_info/'
                f"{classroom_id}/{video_id}/"
            )
            response = session.get(url=url, headers=headers)

            leaf_info = response.json()
            ccid = leaf_info['data']['content_info']['media']['ccid']
            d = leaf_info['data']['content_info']['media']['duration']

            v = str(leaf_info['data']['id'])
            u = str(leaf_info['data']['user_id'])
            timestamp_ms = int(time.time() * 1000)
            url = (
                "https://www.yuketang.cn/video-log/get_video_watch_progress/"
                f"?cid={c_course_id}&user_id={u}&classroom_id={classroom_id}"
                f"&video_type=video&vtype=rate&video_id={video_id}&snapshot=1"
            )
            response_new = session.get(url=url, headers=headers)
            progress_response = response_new.json()
            video_data = progress_response.get('data', {}).get(video_id, {})
            if not video_data and progress_response.get(video_id):
                video_data = progress_response[video_id]

            if d == 0:
                response_new = session.get(url=url, headers=headers)
                progress_response = response_new.json()
                video_data = progress_response.get('data', {}).get(video_id, {}) or progress_response.get(video_id, {})
                try:
                    d = int(video_data.get('video_length', d))
                except Exception:
                    pass

            completed_flag = video_data.get('completed', 0)
            watched_seconds = video_data.get('watch_length', 0)

            if not d or d <= 0:
                log_warning("视频" + video_id + "未获取到有效时长，自动跳过。")
                continue

            def calculate_coverage(watch_len, video_len):
                if not video_len or video_len <= 0:
                    return 0.0
                return min(100.0, (watch_len / video_len) * 100.0)

            COVERAGE_THRESHOLD = 100.0
            initial_coverage = calculate_coverage(watched_seconds, d)
            current_cp = watched_seconds if watched_seconds else random.uniform(
                5, min(60, max(10, d * 0.1)))
            simulated_rate = random.uniform(0.9, 1.25)
            ts_pointer = timestamp_ms

            stuck_reset_notice_shown = False
            last_heartbeat_time = time.time()
            is_restarting = False
            last_watched_before_restart = watched_seconds

            def is_video_completed(watch_len, video_len, server_completed):
                coverage = calculate_coverage(watch_len, video_len)
                if coverage >= COVERAGE_THRESHOLD:
                    return True
                return False

            if is_video_completed(watched_seconds, d, completed_flag):
                log_info(
                    f"视频 {video_id} 覆盖率已达标（{initial_coverage:.1f}% >= {COVERAGE_THRESHOLD}%），跳过。"
                )
                continue
            if completed_flag == 1:
                log_warning(
                    f"视频 {video_id} 服务器标记为完成，但覆盖率仅 {initial_coverage:.1f}%（未达到 {COVERAGE_THRESHOLD}%），继续刷课以提高覆盖率。"
                )

            while not is_video_completed(watched_seconds, d, completed_flag):
                increment = random.uniform(max(2, d * 0.01), max(5, d * 0.05))
                current_cp = min(d, current_cp + increment)
                time_elapsed = (increment / simulated_rate) * 1000
                ts_pointer += int(time_elapsed + random.randint(100, 500))
                progress_percent = int(min(100, (current_cp / d) * 100))
                coverage = calculate_coverage(watched_seconds, d)

                if is_restarting:
                    log_info(
                        f"正在观看第{i + 1}章 第{j + 1}个视频----当前进度：{progress_percent}%（重新播放中），覆盖率：{coverage:.1f}%"
                    )
                else:
                    log_info(
                        f"正在观看第{i + 1}章 第{j + 1}个视频----当前进度：{progress_percent}%，覆盖率：{coverage:.1f}%"
                    )

                current_time = time.time()
                elapsed_since_last = current_time - last_heartbeat_time
                min_interval = 0.5
                max_interval = 1.5
                if elapsed_since_last < min_interval:
                    time.sleep(min_interval - elapsed_since_last)
                elif elapsed_since_last < max_interval:
                    random_sleep_interval()
                last_heartbeat_time = time.time()

                heartbeat_url = 'https://www.yuketang.cn/video-log/heartbeat/'
                payload = {
                    "heart_data": [{
                        "i": random.randint(3, 8),
                        "et": "heartbeat",
                        "p": "web",
                        "n": "ali-cdn.xuetangx.com",
                        "lob": "ykt",
                        "cp": round(current_cp, 2),
                        "fp": random.randint(80, 100),
                        "tp": 100,
                        "sp": random.randint(4, 6),
                        "ts": str(ts_pointer),
                        "u": int(u),
                        "uip": "",
                        "c": int(c_course_id),
                        "v": int(v),
                        "skuid": int(s_id),
                        "classroomid": classroom_id,
                        "cc": ccid,
                        "d": int(d),
                        "pg": video_id + "_x33v",
                        "sq": random.randint(8, 15),
                        "t": "video",
                        "cards_id": 0,
                        "slide": 0,
                        "v_url": ""
                    }]
                }

                headers1 = {
                    'User-Agent': SESSION_USER_AGENT,
                    'Content-Type': 'application/json',
                    'authority': 'changjiang.yuketang.cn',
                    'method': 'GET',
                    'path': '/v2/api/web/courses/list?identity=2',
                    'referer': SESSION_REFERER,
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'same-origin',
                }

                max_retries = 3
                for retry in range(max_retries):
                    try:
                        response = session.post(
                            url=heartbeat_url,
                            data=json.dumps(payload),
                            headers=headers1,
                            timeout=10
                        )
                        if response.status_code == 200:
                            break
                        if retry < max_retries - 1:
                            time.sleep(0.5)
                    except Exception as exc:
                        if retry < max_retries - 1:
                            log_warning(f"心跳发送失败，重试中... ({retry + 1}/{max_retries})")
                            time.sleep(0.5)
                        else:
                            log_error(f"心跳发送失败：{exc}")

                url = (
                    "https://www.yuketang.cn/video-log/get_video_watch_progress/"
                    f"?cid={c_course_id}&user_id={u}&classroom_id={classroom_id}"
                    f"&video_type=video&vtype=rate&video_id={video_id}&snapshot=1"
                )
                try:
                    response_new = session.get(url=url, headers=headers, timeout=10)
                except Exception as exc:
                    log_warning(f"获取进度失败：{exc}，继续下一次心跳")
                    continue
                progress_response = response_new.json()
                video_data = progress_response.get('data', {}).get(video_id, {}) or progress_response.get(video_id, {})
                has_watched = video_data.get('watch_length', 0)
                if d == 0:
                    try:
                        d = int(video_data.get('video_length', d))
                    except Exception:
                        pass

                completed_flag = video_data.get('completed', 0)

                if has_watched is not None:
                    if is_restarting:
                        if has_watched < last_watched_before_restart * 0.8 or has_watched > watched_seconds:
                            watched_seconds = has_watched
                            if has_watched < d * 0.2:
                                is_restarting = False
                                current_cp = max(current_cp, has_watched)
                            else:
                                current_cp = max(current_cp, has_watched)
                    else:
                        if has_watched > current_cp:
                            current_cp = has_watched
                        watched_seconds = has_watched

                current_coverage = calculate_coverage(watched_seconds, d)
                is_completed = is_video_completed(watched_seconds, d, completed_flag)

                if is_completed:
                    log_success(
                        f"视频 {video_id} 覆盖率已达标！当前覆盖率: {current_coverage:.1f}%（达到 {COVERAGE_THRESHOLD}% 阈值），完成。"
                    )
                    break

                if current_cp >= d and current_coverage < COVERAGE_THRESHOLD:
                    if not stuck_reset_notice_shown:
                        log_warning(
                            f"进度达到100%但覆盖率仅 {current_coverage:.1f}%（未达到 {COVERAGE_THRESHOLD}%），重新从头播放以补刷。"
                        )
                        stuck_reset_notice_shown = True
                    current_cp = 0
                    last_watched_before_restart = watched_seconds
                    ts_pointer = int(time.time() * 1000)
                    is_restarting = True
                    random_sleep_interval()
                    continue

    log_success("该课程已完成刷课！")


def _get_csrf_token() -> Optional[str]:
    """
    从当前 session.cookies 中尝试提取 csrf token。
    不同学校可能字段名略有差异，这里做一个尽量兼容的尝试。
    """
    candidates = ['csrftoken', 'csrf_token', 'csrfmiddlewaretoken']
    for name in candidates:
        value = session.cookies.get(name)
        if value:
            return value
    return None


def _get_course_chapter_videos(classroom_id: str, university_id: int) -> List[List[Dict]]:
    """
    通过章节接口补充获取每一章下的视频 leaf。

    返回值为列表，长度与 course_chapter 相同，每个元素是该章的视频 leaf 列表（仅包含 id 字段）。
    """
    url = "https://www.yuketang.cn/mooc-api/v1/lms/learn/course/chapter"
    params = {
        "cid": classroom_id,  # 抓包示例中使用的是 classroom_id
        "term": "latest",
        "uv_id": university_id,
        "classroom_id": classroom_id,
    }

    headers = {
        "accept": "application/json, text/plain, */*",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xtbz": "ykt",
        "x-client": "web",
    }
    csrf = _get_csrf_token()
    if csrf:
        headers["x-csrftoken"] = csrf

    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
    except Exception as exc:
        log_warning(f"调用章节接口获取视频列表失败，将跳过备用解析逻辑：{exc}")
        return []

    chapters = data.get("data", {}).get("course_chapter", [])
    result: List[List[Dict]] = []

    for chapter in chapters:
        chapter_videos: List[Dict] = []
        for sec in chapter.get("section_leaf_list", []):
            leaf_list = sec.get("leaf_list")
            if isinstance(leaf_list, list):
                for leaf in leaf_list:
                    if leaf.get("leaf_type") == 0 and leaf.get("id"):
                        chapter_videos.append({"id": leaf["id"]})
            else:
                # 有些节点本身就是 leaf（比如只有讨论题、测试题），这里也做一下防御性判断
                if sec.get("leaf_type") == 0 and sec.get("id"):
                    chapter_videos.append({"id": sec["id"]})
        result.append(chapter_videos)

    return result


def _extract_sku_id_from_logs(classroom_id: str) -> Optional[int]:
    """
    从学习日志接口中提取 sku_id。
    """
    url = (
        "https://www.yuketang.cn/v2/api/web/logs/learn/"
        f"{classroom_id}?actype=-1&page=0&offset=20&sort=-1"
    )
    response = session.get(url)
    data = response.json()
    activities = data.get('data', {}).get('activities', [])
    for act in activities:
        content = act.get('content') or {}
        if 'sku_id' in content:
            return int(content['sku_id'])
    return None


def _get_score_detail(sku_id: int, classroom_id: str, university_id: int) -> dict:
    """
    调用单个 sku 的 score_detail 接口，返回 JSON。
    """
    url = f"https://www.yuketang.cn/c27/online_courseware/schedule/score_detail/single/{sku_id}/0/"
    headers = {
        "accept": "application/json, text/plain, */*",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xt-agent": "web",
        "xtbz": "ykt",
    }
    response = session.get(url, headers=headers)
    return response.json()


def _iter_discussion_leaf_ids(score_detail: dict):
    """
    从 score_detail 中筛选所有“未得分”的讨论题 leaf_id。

    条件：
    - leaf_type == 4
    - evaluation_id == 10
    - user_score 为 0 或未设置（即当前还没有得分）
    """
    leaf_infos = score_detail.get('data', {}).get('leaf_level_infos', [])
    for item in leaf_infos:
        if (
            item.get('leaf_type') == 4
            and item.get('evaluation_id') == 10
            and item.get('id')
        ):
            # 仅对当前得分为 0 的讨论题生成评论
            user_score = item.get("user_score", 0)
            try:
                user_score_val = float(user_score)
            except (TypeError, ValueError):
                user_score_val = 0.0
            if user_score_val == 0.0:
                yield int(item['id'])


def _get_topic_and_user(classroom_id: str, sku_id: int, leaf_id: int, university_id: int) -> Optional[Tuple[int, int]]:
    """
    根据 classroom_id + sku_id + leaf_id 获取 (topic_id, to_user)。
    """
    url = "https://www.yuketang.cn/v/discussion/v2/unit/discussion/"
    params = {
        "classroom_id": classroom_id,
        "sku_id": sku_id,
        "leaf_id": leaf_id,
        "topic_type": 4,
        "channel": "xt",
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xt-agent": "web",
        "xtbz": "ykt",
    }
    response = session.get(url, params=params, headers=headers)
    data = response.json().get("data") or {}
    user_id = data.get("user_id")
    topic_id = data.get("id")
    if not user_id or not topic_id:
        return None
    return int(topic_id), int(user_id)


def _post_comment(classroom_id: str, university_id: int, topic_id: int, to_user: int, text: str) -> bool:
    """
    向指定话题发送一条评论。
    """
    url = "https://www.yuketang.cn/v/discussion/v2/comment/"
    csrf_token = _get_csrf_token()
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xt-agent": "web",
        "xtbz": "ykt",
    }
    if csrf_token:
        headers["x-csrftoken"] = csrf_token

    payload = {
        "to_user": to_user,
        "topic_id": topic_id,
        "content": {
            "text": text,
            "upload_images": [],
            "accessory_list": [],
        },
    }

    try:
        resp = session.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    except Exception as exc:
        log_error(f"发送评论失败（topic_id={topic_id}）：{exc}")
        return False

    try:
        data = resp.json()
    except Exception:
        data = None

    if resp.status_code == 200 and data and data.get("success"):
        log_success(f"评论成功：topic_id={topic_id}")
        return True

    log_warning(f"评论可能失败，状态码={resp.status_code}，响应={resp.text[:200]}")
    return False


def _get_discussion_leaf_info(classroom_id: str, leaf_id: int, university_id: int) -> Optional[Dict]:
    """
    获取讨论题 leaf 的详细信息，包括题目内容（context）。
    """
    url = (
        "https://www.yuketang.cn/mooc-api/v1/lms/learn/leaf_info/"
        f"{classroom_id}/{leaf_id}/"
    )
    headers = {
        "accept": "application/json, text/plain, */*",
        "classroom-id": str(classroom_id),
        "university-id": str(university_id),
        "uv-id": str(university_id),
        "xt-agent": "web",
        "xtbz": "ykt",
    }
    try:
        resp = session.get(url, headers=headers, timeout=10)
        return resp.json()
    except Exception as exc:
        log_warning(f"获取讨论题 leaf_info 失败（leaf_id={leaf_id}）：{exc}")
        return None




def run_discussion_comment_session():
    """
    自动刷当前课程的所有“讨论题”（leaf_type=4, evaluation_id=10）评论。

    步骤：
    1. 选择课程，得到 classroom_id / university_id；
    2. 从学习日志中提取 sku_id；
    3. 调用 score_detail 接口获取所有讨论题 leaf_id；
    4. 对每个 leaf_id 调用 discussion/unit 接口拿到 topic_id / to_user；
    5. 发送评论。
    """
    classroom_id, university_id, course_info = _select_course()
    log_info(f"当前选择课程：{course_info.get('name')}（classroom_id={classroom_id}）")

    sku_id = _extract_sku_id_from_logs(classroom_id)
  
    if not sku_id:
        log_warning("未从学习日志中找到 sku_id，无法继续自动评论。")
        return
    log_info(f"已获取 sku_id={sku_id}，开始获取讨论题列表。")

    score_detail = _get_score_detail(sku_id=sku_id, classroom_id=classroom_id, university_id=university_id)
    leaf_ids = list(_iter_discussion_leaf_ids(score_detail))

    if not leaf_ids:
        log_warning("在 score_detail 中未找到任何讨论题（leaf_type=4, evaluation_id=10）。")
        return

    log_info(f"检测到 {len(leaf_ids)} 个讨论题，将依次尝试发送评论。")

    default_comment = get_default_comment()

    for idx, leaf_id in enumerate(leaf_ids, start=1):
        log_info(SEPARATOR)
        log_info(f"正在处理第 {idx}/{len(leaf_ids)} 个讨论题，leaf_id={leaf_id}")

        topic_user = _get_topic_and_user(
            classroom_id=classroom_id,
            sku_id=sku_id,
            leaf_id=leaf_id,
            university_id=university_id,
        )
        if not topic_user:
            log_warning(f"获取讨论详情失败，跳过该讨论题（leaf_id={leaf_id}）。")
            continue

        topic_id, to_user = topic_user
        log_info(f"已获取 topic_id={topic_id}, to_user={to_user}，开始准备评论内容。")

        # 先获取讨论题目内容
        leaf_info = _get_discussion_leaf_info(classroom_id, leaf_id, university_id)
        question_html = ""
        if leaf_info and leaf_info.get("data"):
            question_html = (
                leaf_info["data"]
                .get("content_info", {})
                .get("context", "")
            )

        # 根据配置和题目决定最终评论内容
        comment_text: Optional[str]
        use_llm = False
        if default_comment.strip().lower() == "none":
            # 使用 LLM 自动生成，并将课程名称加入提示词
            comment_text = generate_comment_by_llm(
                question_html,
                course_info.get("name"),
            )
            if not comment_text:
                log_warning("LLM 生成评论失败，可能是该问题内容有点敏感，建议手动评论。")
                forum_url = (
                    f"https://www.yuketang.cn/v2/web/lms/{classroom_id}/forum/{leaf_id}?hide_return=1"
                )
                log_info(f"对应讨论区地址：{forum_url}")
                return
            use_llm = True
        else:
            comment_text = default_comment

        # 使用固定模板评论时，为降低频率，随机 sleep 几秒
        if not use_llm:
            delay = random.uniform(3, 8)
            log_info(f"使用固定评论模板，将随机等待 {delay:.1f} 秒后再发送评论，以降低频率。")
            time.sleep(delay)

        log_info("评论内容已生成，开始发送评论。")

        _post_comment(
            classroom_id=classroom_id,
            university_id=university_id,
            topic_id=topic_id,
            to_user=to_user,
            text=comment_text,
        )

    log_success("本课程所有讨论题评论流程已结束。")
