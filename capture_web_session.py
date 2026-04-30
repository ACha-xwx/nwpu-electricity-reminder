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
# A taller mobile viewport keeps the "统一身份认证" option visible
# on the login sheet without asking users to resize the window manually.
MOBILE_VIEWPORT = {"width": 430, "height": 1180, "device_scale_factor": 2}
OUTER_WINDOW_WIDTH = 470
OUTER_WINDOW_HEIGHT = 1480
PROFILE_DIR_NAME = ".browser_profile"
LOGIN_PAGE_MIN_SCALE = 0.86
LOGIN_SHEET_MIN_SCALE = 0.8
LOGIN_VIEWPORT_MARGIN = 28


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


def install_login_page_scale(page):
    page.add_init_script(
        script=f"""
        (() => {{
          const loginPageMinScale = {LOGIN_PAGE_MIN_SCALE};
          const loginSheetMinScale = {LOGIN_SHEET_MIN_SCALE};
          const viewportMargin = {LOGIN_VIEWPORT_MARGIN};
          const loginPageTitle = '\\u6b22\\u8fce\\u767b\\u5f55\\u79fb\\u52a8\\u670d\\u52a1\\u5e73\\u53f0';
          const studentLoginText = '\\u5b66\\u53f7\\u767b\\u5f55';
          const unifiedLoginText = '\\u7edf\\u4e00\\u8eab\\u4efd\\u8ba4\\u8bc1';
          const moreLoginMethodsText = '\\u66f4\\u591a\\u767b\\u5f55\\u65b9\\u5f0f';
          const defaultViewport = 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=yes, viewport-fit=cover';

          const ensureViewport = () =>
            document.querySelector('meta[name="viewport"]') ||
            (() => {{
              const tag = document.createElement('meta');
              tag.name = 'viewport';
              document.head.appendChild(tag);
              return tag;
            }})();

          const applyScale = scale => {{
            const viewport = ensureViewport();
            viewport.setAttribute(
              'content',
              `width=device-width, initial-scale=${{scale}}, maximum-scale=${{scale}}, user-scalable=yes, viewport-fit=cover`
            );
            document.documentElement.style.zoom = String(scale);
            if (document.body) {{
              document.body.style.zoom = String(scale);
            }}
          }};

          const setNormalScale = () => {{
            ensureViewport().setAttribute('content', defaultViewport);
            applyScale(1);
          }};

          const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

          const textOf = node =>
            (node?.innerText || node?.textContent || '').replace(/\\s+/g, ' ').trim();

          const getViewportHeight = () => {{
            const candidates = [
              window.visualViewport ? window.visualViewport.height : 0,
              window.innerHeight || 0,
              document.documentElement ? document.documentElement.clientHeight : 0,
              screen && screen.availHeight ? screen.availHeight : 0,
            ].filter(value => Number.isFinite(value) && value > 0);
            return candidates.length ? Math.min(...candidates) : 0;
          }};

          const findElementByTexts = texts => {{
            const candidates = Array.from(
              document.querySelectorAll('button, a, div, span, p, li, label')
            );
            return candidates.find(node => {{
              const text = textOf(node);
              return texts.every(part => text.includes(part));
            }});
          }};

          const hasLoginSheet = () => {{
            const text = textOf(document.body || document.documentElement);
            return text.includes(studentLoginText) && text.includes(unifiedLoginText);
          }};

          const hasLoginPage = () => {{
            const text = textOf(document.body || document.documentElement);
            return text.includes(loginPageTitle) && text.includes(studentLoginText);
          }};

          const scrollIntoViewRobust = target => {{
            if (!target) {{
              return;
            }}

            if (typeof target.scrollIntoView === 'function') {{
              target.scrollIntoView({{ block: 'center', inline: 'nearest', behavior: 'auto' }});
            }}

            let parent = target.parentElement;
            while (parent) {{
              const style = window.getComputedStyle(parent);
              const scrollable =
                parent.scrollHeight > parent.clientHeight + 12 &&
                /(auto|scroll)/.test(style.overflowY);

              if (scrollable) {{
                const targetTop =
                  target.getBoundingClientRect().top -
                  parent.getBoundingClientRect().top +
                  parent.scrollTop;
                parent.scrollTo({{
                  top: Math.max(0, targetTop - parent.clientHeight * 0.35),
                  behavior: 'auto',
                }});
              }}
              parent = parent.parentElement;
            }}

            const absoluteTop = target.getBoundingClientRect().top + window.scrollY;
            window.scrollTo({{
              top: Math.max(0, absoluteTop - window.innerHeight * 0.65),
              behavior: 'auto',
            }});
          }};

          const fitTargetIntoViewport = (target, minScale) => {{
            if (!target) {{
              return false;
            }}

            scrollIntoViewRobust(target);

            const viewportHeight = getViewportHeight();
            if (!viewportHeight) {{
              return false;
            }}

            const rect = target.getBoundingClientRect();
            const bottomLimit = viewportHeight - viewportMargin;
            const requiredScale =
              rect.bottom > bottomLimit
                ? clamp(bottomLimit / Math.max(rect.bottom, 1), minScale, 1)
                : 1;

            applyScale(requiredScale);
            window.setTimeout(() => scrollIntoViewRobust(target), 40);
            return true;
          }};

          const findLoginSheetContainer = () => {{
            let best = null;
            let bestArea = Number.POSITIVE_INFINITY;

            for (const node of document.querySelectorAll('div, section, article, aside, ul')) {{
              const text = textOf(node);
              if (!text.includes(studentLoginText) || !text.includes(unifiedLoginText)) {{
                continue;
              }}

              const rect = node.getBoundingClientRect();
              const area = rect.width * rect.height;
              if (rect.height > 30 && area < bestArea) {{
                best = node;
                bestArea = area;
              }}
            }}

            return best;
          }};

          const refreshScale = () => {{
            if (hasLoginSheet()) {{
              const sheet = findLoginSheetContainer();
              if (sheet) {{
                sheet.style.maxHeight = '82vh';
                sheet.style.overflowY = 'auto';
                sheet.style.overscrollBehavior = 'contain';
                sheet.style.paddingBottom = '16px';
              }}

              const unifiedLogin = findElementByTexts([unifiedLoginText]);
              fitTargetIntoViewport(unifiedLogin, loginSheetMinScale);
            }} else if (hasLoginPage()) {{
              const moreLoginMethods =
                findElementByTexts([moreLoginMethodsText]) ||
                findElementByTexts([studentLoginText]);
              fitTargetIntoViewport(moreLoginMethods, loginPageMinScale);
            }} else {{
              setNormalScale();
            }}
          }};

          const observer = new MutationObserver(() => {{
            window.setTimeout(refreshScale, 30);
          }});

          document.addEventListener('DOMContentLoaded', () => {{
            refreshScale();
            observer.observe(document.documentElement, {{
              childList: true,
              subtree: true,
              characterData: true,
            }});
          }});

          window.addEventListener('load', refreshScale);
          window.setInterval(refreshScale, 800);
        }})();
        """,
    )


def resize_outer_window(page):
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
                        "width": OUTER_WINDOW_WIDTH,
                        "height": OUTER_WINDOW_HEIGHT,
                        "windowState": "normal",
                    },
                },
            )
    except Exception:
        pass


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
    print("请在浏览器里手动进入“宿舍电费 / 用量查询”页面。")
    print("只有页面里真的写出了会话信息，脚本才会继续抓取。")

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
    print("浏览器已经打开，当前窗口会尽量模拟成手机浏览器。")
    print("请按下面的顺序手动操作：")
    print("1. 点击页面上方的“请登录”按钮。")
    print("2. 在新页面底部点击“更多登录方式”。")
    print("3. 选择“统一身份认证”入口。")
    print("4. 登录你的西北工业大学账号。")
    print("5. 登录成功后，回到移动服务平台页面。")
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
            install_login_page_scale(page)
            page.goto(YKT_HOME_URL, wait_until="domcontentloaded", timeout=60000)
            print_manual_login_steps()
            wait_for_cas_login(context)
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
