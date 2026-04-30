import os
import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

from nwpu_api import DEFAULT_REFERER, extract_remaining_electricity, extract_room_info

DEFAULT_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Mobile Safari/537.36"
)
DEFAULT_MOBILE_VIEWPORT = {"width": 430, "height": 1180}
PLAT_HOME_URL = "https://yktapp.nwpu.edu.cn/plat/shouyeUser"
PROFILE_DIR_NAME = ".browser_profile"


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "没有安装 playwright。请先执行 `pip install playwright`，然后安装浏览器，或直接复用系统里的 Chrome。"
        ) from exc
    return sync_playwright


def find_browser_executable():
    custom_path = os.getenv("PLAYWRIGHT_BROWSER_PATH")
    if custom_path and Path(custom_path).exists():
        return custom_path

    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/snap/bin/chromium"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def build_injected_auth_cookies(auth):
    cookies = []
    for cookie in auth.get("cookie_meta", []):
        name = cookie.get("name", "")
        if not name or name in {"Domain", "Path"}:
            continue

        item = {
            "name": name,
            "value": cookie["value"],
            "domain": cookie["domain"],
            "path": cookie.get("path", "/"),
        }
        if "secure" in cookie:
            item["secure"] = bool(cookie.get("secure"))
        if "httpOnly" in cookie:
            item["httpOnly"] = bool(cookie.get("httpOnly"))
        expires = cookie.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            item["expires"] = expires
        cookies.append(item)
    return cookies


def get_saved_profile_dir():
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
    endpoint = f"http://127.0.0.1:{port}/json/version"
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        try:
            import httpx

            response = httpx.get(endpoint, timeout=2.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)

    raise TimeoutError("等待浏览器调试端口超时。")


def launch_browser_with_profile(browser_path, profile_dir, headless):
    port = get_free_port()
    command = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        f"--window-size={DEFAULT_MOBILE_VIEWPORT['width']},{DEFAULT_MOBILE_VIEWPORT['height']}",
    ]
    if headless:
        command.append("--headless=new")
    command.append("about:blank")

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


def get_or_create_page(context):
    if context.pages:
        return context.pages[0]
    return context.new_page()


def emulate_mobile_browser(context, page, user_agent):
    cdp_session = context.new_cdp_session(page)
    cdp_session.send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": DEFAULT_MOBILE_VIEWPORT["width"],
            "height": DEFAULT_MOBILE_VIEWPORT["height"],
            "deviceScaleFactor": 2,
            "mobile": True,
            "screenOrientation": {"type": "portraitPrimary", "angle": 0},
        },
    )
    cdp_session.send(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": user_agent,
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


def restore_web_storage(page, local_storage, session_storage):
    page.evaluate(
        """
        ({ localStorageEntries, sessionStorageEntries }) => {
          for (const [k, v] of Object.entries(localStorageEntries || {})) {
            localStorage.setItem(k, v);
          }
          for (const [k, v] of Object.entries(sessionStorageEntries || {})) {
            sessionStorage.setItem(k, v);
          }
        }
        """,
        {
            "localStorageEntries": local_storage,
            "sessionStorageEntries": session_storage,
        },
    )


def fetch_electricity_on_page(page, campus, building, room):
    return page.evaluate(
        """
        async ({ campus, building, room }) => {
          const response = await fetch('https://yktapp.nwpu.edu.cn/jfdt/charge/feeitem/getThirdData', {
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
        {"campus": campus, "building": building, "room": room},
    )


def try_replay_targets(page, replay_targets, local_storage, session_storage, campus, building, room):
    result = None
    attempts = []

    for target_url in replay_targets:
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            restore_web_storage(page, local_storage, session_storage)
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1200)

            result = fetch_electricity_on_page(page, campus, building, room)
            status_code = result.get("status")
            if status_code == 200:
                return result, attempts

            body_preview = (result.get("text", "") or "")[:200]
            attempts.append(f"{target_url} -> {status_code}: {body_preview}")
        except Exception as exc:
            attempts.append(f"{target_url} -> navigation error: {exc}")

    return result, attempts


def query_electricity_via_browser(auth, campus, building, room):
    sync_playwright = _load_playwright()
    browser_path = find_browser_executable()
    page_url = auth.get(
        "page_url",
        DEFAULT_REFERER,
    )
    user_agent = auth.get("user_agent", DEFAULT_MOBILE_USER_AGENT)
    local_storage = auth.get("local_storage", {})
    session_storage = auth.get("session_storage", {})
    replay_targets = []
    for candidate in [page_url, auth.get("referer"), PLAT_HOME_URL, DEFAULT_REFERER]:
        if candidate and candidate not in replay_targets:
            replay_targets.append(candidate)

    with sync_playwright() as playwright:
        launch_kwargs = {"headless": os.getenv("PLAYWRIGHT_HEADLESS", "1") != "0"}
        if browser_path:
            launch_kwargs["executable_path"] = browser_path

        attempts = []
        profile_dir = get_saved_profile_dir()
        if profile_dir.exists():
            profile_process = None
            profile_browser = None
            try:
                profile_process, port = launch_browser_with_profile(
                    browser_path,
                    str(profile_dir),
                    headless=launch_kwargs["headless"],
                )
                profile_browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                context = profile_browser.contexts[0] if profile_browser.contexts else profile_browser.new_context()
                page = get_or_create_page(context)
                emulate_mobile_browser(context, page, user_agent)
                result, profile_attempts = try_replay_targets(
                    page,
                    replay_targets,
                    local_storage,
                    session_storage,
                    campus,
                    building,
                    room,
                )
                if result and result.get("status") == 200:
                    body = result.get("text", "")
                    payload = __import__("json").loads(body)
                    data = payload["map"]
                    return extract_remaining_electricity(data), extract_room_info(data)
                attempts.extend(profile_attempts)
            except Exception as exc:
                attempts.append(f"profile replay error: {exc}")
            finally:
                if profile_browser is not None:
                    profile_browser.close()
                close_browser_process(profile_process)

        browser = playwright.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(
                user_agent=user_agent,
                viewport=DEFAULT_MOBILE_VIEWPORT,
                is_mobile=True,
                has_touch=True,
                device_scale_factor=2,
                locale="zh-CN",
            )
            auth_cookies = build_injected_auth_cookies(auth)
            if auth_cookies:
                context.add_cookies(auth_cookies)

            page = context.new_page()
            emulate_mobile_browser(context, page, user_agent)
            result, fresh_attempts = try_replay_targets(
                page,
                replay_targets,
                local_storage,
                session_storage,
                campus,
                building,
                room,
            )
            attempts.extend(fresh_attempts)
        finally:
            browser.close()

    status_code = result.get("status")
    body = result.get("text", "")
    if status_code != 200:
        attempt_text = " | ".join(attempts) if attempts else body[:200]
        raise RuntimeError(f"浏览器会话取数失败，状态码 {status_code}：{attempt_text}")

    import json

    payload = json.loads(body)
    data = payload["map"]
    return extract_remaining_electricity(data), extract_room_info(data)
