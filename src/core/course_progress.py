import json
import random
import time

from src.network.http_client import SEPARATOR, SESSION_REFERER, SESSION_USER_AGENT, session
from src.utils.logging_utils import log_error, log_info, log_success, log_warning


def random_sleep_interval():
    """随机心跳睡眠，避免被判异常。"""
    base = random.uniform(0.3, 0.8)
    if random.random() < 0.1:
        base += random.uniform(0.5, 1.5)
    time.sleep(base)


def run_course_session():
    """选择课程并持续刷课。"""
    url = 'https://www.yuketang.cn/v2/api/web/courses/list?identity=2'
    response = session.get(url=url)

    course_response = response.json()
    course_list = course_response.get('data', {}).get('list', [])

    if len(course_list) > 1:
        for i, course in enumerate(course_list):
            log_info(f"序号：{i} ----- {course['name']}")
        log_info(SEPARATOR)

        min_value = 0
        max_value = len(course_list) - 1

        while True:
            user_input = input("请输入需要刷课的课程编号：\n")
            try:
                num = int(user_input)
                if min_value <= num <= max_value:
                    classroom_id = str(course_list[num]['classroom_id'])
                    url = (
                        "https://www.yuketang.cn/v2/api/web/logs/learn/"
                        f"{classroom_id}?actype=-1&page=0&offset=20&sort=-1"
                    )
                    response = session.get(url)
                    course_logs = response.json()
                    break
                log_warning(f"输入错误，请输入一个介于 {min_value} 和 {max_value} 之间的课程编号。")
            except ValueError:
                log_warning("输入错误，请确保您输入的是一个整数。")
    else:
        log_warning("未检测到课程数据，请检查是否登录成功。")
        raise SystemExit(-1)

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

    for i, chapter in enumerate(courseware_detail['data']['content_info']):
        video_leafs = extract_video_leafs(chapter)
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


