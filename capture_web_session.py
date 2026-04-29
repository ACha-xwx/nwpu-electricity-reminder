import json
import shutil
import tempfile
import time

from browser_session import _load_playwright, find_browser_executable
from capture_android_session import update_config_with_state
from nwpu_api import DEFAULT_REFERER, dump_config, get_config_path, load_config_or_empty

YKT_HOME_URL = "https://yktapp.nwpu.edu.cn/plat/shouyeUser"
YKT_API_URL = "https://yktapp.nwpu.edu.cn/jfdt/charge/feeitem/getThirdData"
FALLBACK_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UQ1A.240205.002; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/125.0.0.0 "
    "Mobile Safari/537.36"
)


def build_cookie_payload(cookies):
    cookie_dict = {}
    cookie_meta = []

    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue

        cookie_dict[name] = value
        cookie_meta.append(
            {
                "name": name,
                "value": value,
                "domain": cookie.get("domain"),
                "path": cookie.get("path", "/"),
                "secure": bool(cookie.get("secure")),
                "httpOnly": bool(cookie.get("httpOnly")),
                "expires": cookie.get("expires", -1),
                "session": bool(cookie.get("session", True)),
            }
        )

    return cookie_dict, cookie_meta


def read_sceneinfo(page):
    try:
        return page.evaluate("() => sessionStorage.getItem('sceneinfo')")
    except Exception:
        return None


def read_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""


def try_click_text(page, labels, timeout_ms=2500):
    for label in labels:
        for locator in (
            page.get_by_text(label, exact=True).first,
            page.get_by_text(label, exact=False).first,
        ):
            try:
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
            except Exception:
                pass
            try:
                locator.click(timeout=timeout_ms)
                return label
            except Exception:
                continue
    return None


def wait_for_cas_login(context, timeout_seconds=300):
    print("正在等待统一身份认证登录完成。")

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        cookies = context.cookies()
        if any(cookie.get("name") == "TGC" for cookie in cookies):
            print("检测到统一身份认证登录成功。")
            return
        time.sleep(1)

    raise TimeoutError("等待统一身份认证登录超时。请重新运行脚本后再试。")


def wait_for_ykt_page(page, timeout_seconds=300):
    print("接下来脚本会打开电费页面。")
    print("如果页面没有自动进入宿舍电费查询，请手动在浏览器里进入“宿舍电费 / 用量查询”页面。")

    start_time = time.time()
    last_url = ""

    while time.time() - start_time < timeout_seconds:
        current_url = page.url
        if current_url != last_url:
            print(f"当前页面：{current_url}")
            last_url = current_url

        scene_raw = read_sceneinfo(page)
        if scene_raw:
            print("检测到电费页面会话信息。")
            return current_url, json.loads(scene_raw)

        time.sleep(1)

    raise TimeoutError("等待电费页面超时。请确认你已经在浏览器里打开了宿舍电费页面。")


def read_browser_state(context, page):
    current_url = page.url or DEFAULT_REFERER
    user_agent = page.evaluate("() => navigator.userAgent")
    local_storage = page.evaluate(
        "() => Object.fromEntries(Array.from({ length: localStorage.length }, (_, i) => [localStorage.key(i), localStorage.getItem(localStorage.key(i))]))"
    )
    session_storage = page.evaluate(
        "() => Object.fromEntries(Array.from({ length: sessionStorage.length }, (_, i) => [sessionStorage.key(i), sessionStorage.getItem(sessionStorage.key(i))]))"
    )
    cookies = context.cookies()
    cookie_dict, cookie_meta = build_cookie_payload(cookies)
    scene_raw = read_sceneinfo(page)
    scene = json.loads(scene_raw) if scene_raw else {}

    return {
        "page_url": current_url,
        "user_agent": user_agent,
        "local_storage": local_storage,
        "session_storage": session_storage,
        "cookies": cookie_dict,
        "cookie_meta": cookie_meta,
        "scene": scene,
    }


def query_current_room_from_page(page, scene):
    scene_items = {}
    for item in scene.get("data", []):
        key = item.get("key")
        if key:
            scene_items[key] = item

    required_keys = ("campus", "building", "room")
    if not all(key in scene_items for key in required_keys):
        return None

    params = {
        "campus": scene_items["campus"]["id"],
        "building": scene_items["building"]["id"],
        "room": scene_items["room"]["id"],
    }

    result = page.evaluate(
        """
        async ({ apiUrl, campus, building, room }) => {
          const response = await fetch(apiUrl, {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
              'X-Requested-With': 'XMLHttpRequest'
            },
            body: new URLSearchParams({
              feeitemid: '182',
              type: 'IEC',
              level: '3',
              campus,
              building,
              room
            })
          });

          return {
            status: response.status,
            text: await response.text()
          };
        }
        """,
        {"apiUrl": YKT_API_URL, **params},
    )

    return params, result


def get_launch_user_agent():
    config = load_config_or_empty(get_config_path())
    auth = config.get("auth", {})
    return auth.get("user_agent") or FALLBACK_MOBILE_USER_AGENT


def open_unified_auth_login(page, timeout_seconds=90):
    print("正在自动打开统一身份认证登录入口。")
    entry_labels = [
        "请登录",
        "登录",
    ]
    more_login_labels = [
        "更多登录方式",
    ]
    unified_auth_labels = [
        "统一身份认证",
        "统一身份登录",
    ]

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        current_url = page.url or ""
        if "uis.nwpu.edu.cn/cas/login" in current_url:
            print("已进入统一身份认证页面。")
            return

        clicked = try_click_text(page, unified_auth_labels)
        if clicked:
            print(f"已点击：{clicked}")
            page.wait_for_timeout(4000)
            continue

        clicked = try_click_text(page, more_login_labels)
        if clicked:
            print(f"已点击：{clicked}")
            page.wait_for_timeout(2000)
            continue

        clicked = try_click_text(page, entry_labels)
        if clicked:
            print(f"已点击：{clicked}")
            page.wait_for_timeout(2000)
            continue

        time.sleep(1)

    raise TimeoutError("自动打开统一身份认证入口超时。请确认页面已经正常加载。")


def drive_to_electricity_page(page, timeout_seconds=120):
    print("正在自动进入宿舍电费页面。")
    login_labels = [
        "统一身份登录",
        "统一身份认证登录",
        "统一身份认证",
        "身份登录",
    ]
    electricity_labels = [
        "学生电费",
        "宿舍电费",
        "宿舍电费/用量查询",
        "宿舍电费 / 用量查询",
        "用量查询",
    ]
    unauthorized_markers = [
        "\"code\":401",
        "请求未授权",
        "未授权",
    ]

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        if read_sceneinfo(page):
            print("电费页面会话已经就绪。")
            return

        current_url = page.url or ""
        body_text = read_body_text(page)

        clicked = try_click_text(page, login_labels)
        if clicked:
            print(f"已点击：{clicked}")
            page.wait_for_timeout(5000)
            continue

        clicked = try_click_text(page, electricity_labels)
        if clicked:
            print(f"已点击：{clicked}")
            page.wait_for_timeout(5000)
            continue

        if any(marker in body_text for marker in unauthorized_markers):
            print("页面仍然未授权，正在重新打开移动服务平台首页。")
            page.goto(YKT_HOME_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            continue

        if "berserker-auth/cas/login" in current_url:
            print("当前还停在认证跳转页，正在重新打开移动服务平台首页。")
            page.goto(YKT_HOME_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            continue

        if current_url.startswith("https://yktapp.nwpu.edu.cn/jfdt") and not body_text.strip():
            print("电费页面暂时是空白页，正在回到移动服务平台首页重试。")
            page.goto(YKT_HOME_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            continue

        time.sleep(1)


def main():
    sync_playwright = _load_playwright()
    browser_path = find_browser_executable()
    if not browser_path:
        raise RuntimeError("没有找到 Chrome 或 Edge。请先安装浏览器，或设置 PLAYWRIGHT_BROWSER_PATH。")

    temp_profile_dir = tempfile.mkdtemp(prefix="nwpu_web_capture_")
    launch_user_agent = get_launch_user_agent()

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=temp_profile_dir,
            executable_path=browser_path,
            headless=False,
            user_agent=launch_user_agent,
            locale="zh-CN",
            viewport={"width": 430, "height": 932},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=2,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(YKT_HOME_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            open_unified_auth_login(page)
            wait_for_cas_login(context)

            page.goto(YKT_HOME_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            drive_to_electricity_page(page)
            current_url, scene = wait_for_ykt_page(page)

            browser_state = read_browser_state(context, page)
            config_path = get_config_path()
            config = load_config_or_empty(config_path)
            config = update_config_with_state(
                config,
                browser_state["scene"],
                user_agent=browser_state["user_agent"],
                referer=current_url or DEFAULT_REFERER,
                cookies=browser_state["cookies"],
                cookie_meta=browser_state["cookie_meta"],
                local_storage=browser_state["local_storage"],
                session_storage=browser_state["session_storage"],
            )
            dump_config(config_path, config)

            print(f"配置文件已写入：{config_path}")
            if config.get("room_display"):
                print(f"识别到的宿舍：{config['room_display']}")

            query_result = query_current_room_from_page(page, scene)
            if query_result is None:
                print("这次没有从页面里识别出完整的宿舍参数。")
                print("如果后面查询失败，可以再运行 bind_room.py 手动重新选宿舍。")
                return

            params, result = query_result
            print(f"页面内查询状态码：{result['status']}")
            if result["status"] == 200:
                payload = json.loads(result["text"])
                room_data = payload["map"]["data"]
                show_data = payload["map"]["showData"]
                remaining = show_data.get("当前剩余电量")
                if remaining is None:
                    for key, value in show_data.items():
                        if "剩余电量" in key:
                            remaining = value
                            break

                print(
                    "页面内查询成功："
                    f"{room_data.get('campus', '')} {room_data.get('building', '')} {room_data.get('room', '')}，"
                    f"当前剩余电量 {remaining}"
                )
            else:
                print("已经抓到浏览器会话，但页面内测试查询没有返回 200。")
                print(result["text"][:300])
                print("你仍然可以继续运行 check_electricity.py 或 check_electricity_linux.py 再试。")
        finally:
            context.close()
            shutil.rmtree(temp_profile_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
