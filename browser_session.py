import os
from pathlib import Path

from nwpu_api import extract_remaining_electricity, extract_room_info


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
        if not name or name.startswith("Fkjfy") or name in {"Domain", "Path"}:
            continue

        cookies.append(
            {
                "name": name,
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie.get("path", "/"),
            }
        )
    return cookies


def query_electricity_via_browser(auth, campus, building, room):
    sync_playwright = _load_playwright()
    browser_path = find_browser_executable()
    page_url = auth.get(
        "page_url",
        "https://yktapp.nwpu.edu.cn/jfdt/#/pays/useList?id=182&record=5&defaultDays=7&dateRangeMonths=3",
    )
    user_agent = auth.get("user_agent", "Mozilla/5.0")
    local_storage = auth.get("local_storage", {})
    session_storage = auth.get("session_storage", {})

    with sync_playwright() as playwright:
        launch_kwargs = {"headless": os.getenv("PLAYWRIGHT_HEADLESS", "1") != "0"}
        if browser_path:
            launch_kwargs["executable_path"] = browser_path

        browser = playwright.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(
                user_agent=user_agent,
                viewport={"width": 430, "height": 932},
                locale="zh-CN",
            )
            page = context.new_page()
            page.goto("https://yktapp.nwpu.edu.cn/jfdt/", wait_until="networkidle", timeout=60000)

            auth_cookies = build_injected_auth_cookies(auth)
            if auth_cookies:
                context.add_cookies(auth_cookies)

            page.evaluate(
                "(entries) => { for (const [k, v] of Object.entries(entries)) localStorage.setItem(k, v); }",
                local_storage,
            )
            page.evaluate(
                "(entries) => { for (const [k, v] of Object.entries(entries)) sessionStorage.setItem(k, v); }",
                session_storage,
            )
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)

            result = page.evaluate(
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
        finally:
            browser.close()

    status_code = result.get("status")
    body = result.get("text", "")
    if status_code != 200:
        raise RuntimeError(f"浏览器会话取数失败，状态码 {status_code}：{body[:200]}")

    import json

    payload = json.loads(body)
    data = payload["map"]
    return extract_remaining_electricity(data), extract_room_info(data)
