import json
import os
import socket
import subprocess
import shutil
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx
from browser_session import _load_playwright, find_browser_executable
from nwpu_api import DEFAULT_REFERER, dump_config, get_config_path, load_config_or_empty

YKT_HOME_URL = "https://yktapp.nwpu.edu.cn/plat/shouyeUser"
YKT_API_URL = "https://yktapp.nwpu.edu.cn/jfdt/charge/feeitem/getThirdData"
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Mobile Safari/537.36"
)
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_VIEWPORT = {"width": 430, "height": 1180, "device_scale_factor": 2}
OUTER_WINDOW_WIDTH = 470
OUTER_WINDOW_HEIGHT = 1480
DESKTOP_VIEWPORT = {"width": 1280, "height": 900, "device_scale_factor": 1}
DESKTOP_WINDOW_WIDTH = 1280
DESKTOP_WINDOW_HEIGHT = 900
PROFILE_DIR_NAME = ".browser_profile"
YKT_UNIFIED_LOGIN_URL = (
    "https://yktapp.nwpu.edu.cn/berserker-auth/cas/login/wisedu"
    "?targetUrl=https%3A%2F%2Fyktapp.nwpu.edu.cn%2Fplat%2FshouyeUser"
)


def update_config_with_state(
    config,
    scene,
    user_agent,
    referer,
    cookies,
    cookie_meta,
    local_storage,
    session_storage,
):
    scene_items = {}
    for item in scene.get("data", []):
        key = item.get("key")
        if key:
            scene_items[key] = item

    if "campus" in scene_items:
        config["campus"] = scene_items["campus"].get("id")
    if "building" in scene_items:
        config["building"] = scene_items["building"].get("id")
    if "room" in scene_items:
        config["room"] = scene_items["room"].get("id")

    if "warning_electric" not in config:
        config["warning_electric"] = 10

    if scene.get("dataStr"):
        config["room_display"] = scene["dataStr"]

    config["auth"] = {
        "user_agent": user_agent,
        "referer": referer,
        "origin": "https://yktapp.nwpu.edu.cn",
        "cookies": cookies,
        "cookie_meta": cookie_meta,
        "local_storage": local_storage,
        "session_storage": session_storage,
        "page_url": referer,
    }
    return config


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


def get_saved_profile_dir(config_path=None):
    if os.name == "nt":
        base_dir = Path(os.getenv("LOCALAPPDATA", Path.home()))
    else:
        base_dir = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base_dir / "nwpu-electricity-reminder" / PROFILE_DIR_NAME


def get_free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_debug_endpoint(port, timeout_seconds=20):
    start_time = time.time()
    endpoint = f"http://127.0.0.1:{port}/json/version"

    while time.time() - start_time < timeout_seconds:
        try:
            response = httpx.get(endpoint, timeout=2.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)

    raise TimeoutError("等待浏览器调试端口超时。请确认 Chrome 或 Edge 已经成功启动。")


def launch_debug_browser(browser_path, user_data_dir):
    port = get_free_port()
    command = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--new-window",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--window-position=0,0",
        f"--window-size={OUTER_WINDOW_WIDTH},{OUTER_WINDOW_HEIGHT}",
        "about:blank",
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_for_debug_endpoint(port)
    return process, port


def close_browser_process(process):
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def emulate_mobile_browser(context, page):
    cdp_session = context.new_cdp_session(page)
    cdp_session.send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": MOBILE_VIEWPORT["width"],
            "height": MOBILE_VIEWPORT["height"],
            "deviceScaleFactor": MOBILE_VIEWPORT["device_scale_factor"],
            "mobile": True,
            "screenOrientation": {"type": "portraitPrimary", "angle": 0},
        },
    )
    cdp_session.send(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": MOBILE_USER_AGENT,
            "platform": "Android",
        },
    )
    cdp_session.send(
        "Emulation.setTouchEmulationEnabled",
        {
            "enabled": True,
            "maxTouchPoints": 5,
        },
    )


def emulate_desktop_browser(context, page):
    cdp_session = context.new_cdp_session(page)
    cdp_session.send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": DESKTOP_VIEWPORT["width"],
            "height": DESKTOP_VIEWPORT["height"],
            "deviceScaleFactor": DESKTOP_VIEWPORT["device_scale_factor"],
            "mobile": False,
            "screenOrientation": {"type": "landscapePrimary", "angle": 0},
        },
    )
    cdp_session.send(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": DESKTOP_USER_AGENT,
            "platform": "Windows",
        },
    )
    cdp_session.send(
        "Emulation.setTouchEmulationEnabled",
        {
            "enabled": False,
        },
    )


def install_login_helper(page):
    page.add_init_script(
        script=f"""
        (() => {{
          const unifiedLoginUrl = {json.dumps(YKT_UNIFIED_LOGIN_URL, ensure_ascii=False)};
          const helperId = 'nwpu-electricity-login-helper';
          const loginPageTitle = '\\u6b22\\u8fce\\u767b\\u5f55\\u79fb\\u52a8\\u670d\\u52a1\\u5e73\\u53f0';
          const unifiedLoginText = '\\u7edf\\u4e00\\u8eab\\u4efd\\u8ba4\\u8bc1';
          const moreLoginMethodsText = '\\u66f4\\u591a\\u767b\\u5f55\\u65b9\\u5f0f';
          const studentLoginText = '\\u5b66\\u53f7\\u767b\\u5f55';
          const accountPlaceholder = '\\u8bf7\\u8f93\\u5165\\u5b66\\u53f7';
          const loginButtonText = '\\u767b\\u5f55';

          const pageText = () =>
            (document.body?.innerText || document.body?.textContent || '').replace(/\\s+/g, ' ').trim();

          const isLoginLikePage = () => {{
            if (location.hostname !== 'yktapp.nwpu.edu.cn') {{
              return false;
            }}

            const text = pageText();
            return (
              text.includes(moreLoginMethodsText) ||
              text.includes(unifiedLoginText) ||
              text.includes(studentLoginText) ||
              (text.includes(loginPageTitle) && text.includes(loginButtonText)) ||
              (text.includes(accountPlaceholder) && text.includes(loginButtonText))
            );
          }};

          const ensureHelper = () => {{
            if (!document.body) {{
              return;
            }}

            let helper = document.getElementById(helperId);
            if (!helper) {{
              helper = document.createElement('button');
              helper.id = helperId;
              helper.type = 'button';
              helper.textContent = '\\u7edf\\u4e00\\u8eab\\u4efd\\u8ba4\\u8bc1\\u5165\\u53e3';
              helper.setAttribute('aria-label', '\\u6253\\u5f00\\u7edf\\u4e00\\u8eab\\u4efd\\u8ba4\\u8bc1\\u5165\\u53e3');
              helper.style.cssText = [
                'position:fixed',
                'right:12px',
                'top:12px',
                'z-index:2147483647',
                'border:0',
                'border-radius:999px',
                'padding:10px 14px',
                'background:#1d4ed8',
                'color:#fff',
                'font-size:14px',
                'font-weight:700',
                'line-height:1',
                'box-shadow:0 8px 24px rgba(29,78,216,.28)',
                'cursor:pointer',
              ].join(';');
              helper.addEventListener('click', () => {{
                window.location.href = unifiedLoginUrl;
              }});
              document.body.appendChild(helper);
            }}

            helper.style.display = isLoginLikePage() ? 'block' : 'none';
          }};

          const observer = new MutationObserver(() => {{
            window.setTimeout(ensureHelper, 30);
          }});

          document.addEventListener('DOMContentLoaded', () => {{
            ensureHelper();
            observer.observe(document.documentElement, {{
              childList: true,
              subtree: true,
              characterData: true,
            }});
          }});

          window.addEventListener('load', ensureHelper);
          window.setInterval(ensureHelper, 800);
        }})();
        """,
    )


def resize_outer_window(page, width=OUTER_WINDOW_WIDTH, height=OUTER_WINDOW_HEIGHT):
    cdp_session = page.context.new_cdp_session(page)
    try:
        window_info = cdp_session.send("Browser.getWindowForTarget")
        window_id = window_info.get("windowId")
        if window_id:
            cdp_session.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window_id,
                    "bounds": {
                        "left": 0,
                        "top": 0,
                        "width": width,
                        "height": height,
                        "windowState": "normal",
                    },
                },
            )
    except Exception:
        pass


def sync_browser_mode_for_url(context, page, last_mode=None):
    url = page.url or ""
    mode = "desktop" if "uis.nwpu.edu.cn" in url else "mobile"
    if mode == last_mode:
        return last_mode

    if mode == "desktop":
        emulate_desktop_browser(context, page)
        resize_outer_window(page, DESKTOP_WINDOW_WIDTH, DESKTOP_WINDOW_HEIGHT)
        print("已切换到电脑端模式，请在统一身份认证页面完成登录。")
    else:
        emulate_mobile_browser(context, page)
        resize_outer_window(page)
        print("已切换回手机端模式，请继续进入电费页面。")

    return mode


def sync_browser_mode_for_url_and_reload(context, page, last_mode=None):
    previous_url = page.url or ""
    next_mode = sync_browser_mode_for_url(context, page, last_mode)
    if next_mode == last_mode:
        return last_mode

    should_reload = (
        last_mode is not None
        and ("uis.nwpu.edu.cn" in previous_url or "yktapp.nwpu.edu.cn" in previous_url)
    )
    if should_reload:
        try:
            page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

    return next_mode


def wait_for_cas_login(context, page, timeout_seconds=300):
    print("正在等待统一身份认证登录完成。")

    start_time = time.time()
    browser_mode = None
    while time.time() - start_time < timeout_seconds:
        browser_mode = sync_browser_mode_for_url_and_reload(context, page, browser_mode)
        cookies = context.cookies()
        if any(cookie.get("name") == "TGC" for cookie in cookies):
            print("检测到统一身份认证登录成功。")
            return
        time.sleep(1)

    raise TimeoutError("等待统一身份认证登录超时。请重新运行脚本后再试。")


def wait_for_ykt_page(context, page, timeout_seconds=300):
    print("请在浏览器里手动进入“宿舍电费 / 用量查询”页面。")
    print("只有页面里真的写出了会话信息，脚本才会继续抓取。")

    start_time = time.time()
    last_url = ""
    browser_mode = None

    while time.time() - start_time < timeout_seconds:
        browser_mode = sync_browser_mode_for_url_and_reload(context, page, browser_mode)
        current_url = page.url
        if current_url != last_url:
            print(f"当前页面：{current_url}")
            last_url = current_url

        scene_raw = read_sceneinfo(page)
        if scene_raw:
            print("检测到电费页面会话信息。")
            return current_url, json.loads(scene_raw)

        time.sleep(1)

    raise TimeoutError("等待电费页面超时。请重新运行脚本，并手动进入宿舍电费页面后再试。")


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


def print_manual_login_steps():
    print("浏览器已经打开。")
    print("请按下面的顺序手动操作：")
    print("1. 点击页面上方的“请登录”按钮。")
    print("2. 在新页面底部点击“更多登录方式”，再选择“统一身份认证”。")
    print("3. 如果看不到底部入口，直接点击页面右上角的蓝色“统一身份认证入口”按钮。")
    print("4. 进入统一身份认证后，脚本会自动切换成电脑端窗口，请正常登录。")
    print("5. 登录完成回到移动服务平台后，脚本会自动切回手机端。")
    print("6. 点击“学生电费”或“宿舍电费 / 用量查询”。")
    print("7. 进入电费页面后，先不要关浏览器，等脚本继续抓取。")


def get_or_create_page(context):
    for page in context.pages:
        url = page.url or ""
        if "yktapp.nwpu.edu.cn" in url:
            return page

    if context.pages:
        return context.pages[0]
    return context.new_page()


def main():
    sync_playwright = _load_playwright()
    browser_path = find_browser_executable()
    if not browser_path:
        raise RuntimeError("没有找到 Chrome 或 Edge。请先安装浏览器，或设置 PLAYWRIGHT_BROWSER_PATH。")

    with sync_playwright() as playwright:
        temp_profile_dir = tempfile.mkdtemp(prefix="nwpu_web_capture_")
        context = None
        browser = None
        browser_process = None
        save_profile = False
        saved_profile_dir = get_saved_profile_dir()
        try:
            print("正在启动一个手机样式的 Chrome / Edge 窗口。")
            browser_process, port = launch_debug_browser(browser_path, temp_profile_dir)
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = get_or_create_page(context)
            resize_outer_window(page)
            emulate_mobile_browser(context, page)
            install_login_helper(page)
            page.goto(YKT_HOME_URL, wait_until="domcontentloaded", timeout=60000)
            print_manual_login_steps()
            wait_for_cas_login(context, page)
            current_url, scene = wait_for_ykt_page(context, page)

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
                save_profile = True
            else:
                print("已经抓到浏览器会话，但页面内测试查询没有返回 200。")
                print(result["text"][:300])
                print("你仍然可以继续运行 check_electricity.py 或 check_electricity_linux.py 再试。")
        finally:
            if browser is not None:
                browser.close()
            close_browser_process(browser_process)
            if save_profile:
                saved_profile_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.rmtree(saved_profile_dir, ignore_errors=True)
                shutil.copytree(temp_profile_dir, saved_profile_dir)
                print(f"浏览器会话目录已更新：{saved_profile_dir}")
            shutil.rmtree(temp_profile_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
