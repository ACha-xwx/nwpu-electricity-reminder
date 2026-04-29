import json
import os
import shutil
import socket
import subprocess
from contextlib import closing
from pathlib import Path

import httpx
import websocket

from nwpu_api import DEFAULT_REFERER, extract_remaining_electricity, extract_room_info

PACKAGE_NAME = "com.lantu.MobileCampus.nwpu"
PAGE_KEYWORDS = ("宿舍电费", "用量查询", "/jfdt/#/pays", "/jfdt/#/pays/useList")


def run_adb(adb_path, *args):
    result = subprocess.run(
        [adb_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def find_adb():
    candidates = []
    env_path = shutil.which("adb")
    if env_path:
        candidates.append(env_path)

    custom_env = os.getenv("ADB_PATH")
    if custom_env:
        candidates.append(custom_env)

    project_dir = Path(__file__).resolve().parent
    candidates.extend(
        [
            project_dir.parent / "platform-tools" / "adb.exe",
            project_dir.parent / "platform-tools" / "adb",
            Path("D:/Projects/platform-tools/adb.exe"),
        ]
    )

    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate_path.exists():
            return str(candidate_path)

    adb_path = shutil.which("adb")
    if not adb_path:
        raise FileNotFoundError("没有找到 adb。请先安装 Android Platform Tools，或者把 adb 加到 PATH。")
    return adb_path


def ensure_single_device(adb_path):
    output = run_adb(adb_path, "devices")
    devices = []
    for line in output.splitlines():
        if "\tdevice" in line:
            devices.append(line.split("\t", 1)[0].strip())

    if not devices:
        raise RuntimeError("没有检测到已授权的安卓设备。请确认已经打开 USB 调试，并且点过允许调试。")
    if len(devices) > 1:
        raise RuntimeError(f"检测到多台设备：{devices}。请先只保留一台手机连接。")
    return devices[0]


def get_package_pids(adb_path):
    output = run_adb(adb_path, "shell", "ps", "-A")
    pids = []
    for line in output.splitlines():
        if PACKAGE_NAME not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pid = parts[1]
        if pid.isdigit():
            pids.append(pid)
    return pids


def get_free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def cleanup_forwards(adb_path, forwards):
    for forward in forwards:
        try:
            run_adb(adb_path, "forward", "--remove", forward)
        except Exception:
            pass


def find_target_page(adb_path, pids):
    forwards = []
    for pid in pids:
        port = get_free_port()
        run_adb(adb_path, "forward", f"tcp:{port}", f"localabstract:webview_devtools_remote_{pid}")
        forward_name = f"tcp:{port}"
        forwards.append(forward_name)
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/json", timeout=5.0)
            pages = response.json()
        except Exception:
            continue

        for page in pages:
            page_url = page.get("url", "")
            page_title = page.get("title", "")
            if any(keyword in page_url or keyword in page_title for keyword in PAGE_KEYWORDS):
                return port, page, forwards

    cleanup_forwards(adb_path, forwards)
    raise RuntimeError("没有找到宿舍电费页面。请先在手机里打开校园 App，并进入“宿舍电费 / 用量查询”页面后再试。")


def cdp_call(ws, msg_id, method, params=None):
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == msg_id:
            return message


def read_runtime_value(ws, msg_id, expression):
    result = cdp_call(
        ws,
        msg_id,
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    return result.get("result", {}).get("result", {}).get("value")


def capture_auth_and_scene(page):
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)
    try:
        cdp_call(ws, 1, "Runtime.enable")
        cdp_call(ws, 2, "Network.enable")
        current_url = read_runtime_value(ws, 10, "location.href")
        scene_raw = read_runtime_value(ws, 11, "sessionStorage.getItem('sceneinfo')")
        user_agent = read_runtime_value(ws, 12, "navigator.userAgent")
        local_storage_raw = read_runtime_value(ws, 13, "JSON.stringify(localStorage)")
        session_storage_raw = read_runtime_value(ws, 14, "JSON.stringify(sessionStorage)")
        cookies_result = cdp_call(
            ws,
            15,
            "Network.getCookies",
            {"urls": [current_url or DEFAULT_REFERER]},
        )
    finally:
        ws.close()

    scene = json.loads(scene_raw) if scene_raw else {}
    local_storage = json.loads(local_storage_raw) if local_storage_raw else {}
    session_storage = json.loads(session_storage_raw) if session_storage_raw else {}
    cookies = {}
    cookie_meta = []

    for cookie in cookies_result.get("result", {}).get("cookies", []):
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        if name in {"Domain", "Path"}:
            continue
        cookies[name] = value
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

    return current_url, scene, cookies, cookie_meta, local_storage, session_storage, user_agent


def query_electricity_via_page(page, campus, building, room):
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)
    try:
        cdp_call(ws, 1, "Runtime.enable")
        fetch_expression = f"""
        fetch('https://yktapp.nwpu.edu.cn/jfdt/charge/feeitem/getThirdData', {{
          method: 'POST',
          credentials: 'include',
          headers: {{
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest'
          }},
          body: new URLSearchParams({{
            feeitemid:'182',
            type:'IEC',
            level:'3',
            campus:'{campus}',
            building:'{building}',
            room:'{room}'
          }})
        }}).then(async r => ({{status: r.status, text: await r.text()}}))
        """
        result = cdp_call(
            ws,
            2,
            "Runtime.evaluate",
            {
                "expression": fetch_expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
    finally:
        ws.close()

    value = result.get("result", {}).get("result", {}).get("value", {})
    status_code = value.get("status")
    text = value.get("text", "")
    if status_code != 200:
        raise RuntimeError(f"安卓页面内请求失败，状态码 {status_code}：{text[:200]}")

    payload = json.loads(text)
    data = payload["map"]
    return extract_remaining_electricity(data), extract_room_info(data)


def query_electricity_via_android(campus, building, room):
    adb_path = find_adb()
    ensure_single_device(adb_path)
    pids = get_package_pids(adb_path)
    if not pids:
        raise RuntimeError("没有找到校园 App 进程。请先打开校园 App。")

    _, page, forwards = find_target_page(adb_path, pids)
    try:
        return query_electricity_via_page(page, campus, building, room)
    finally:
        cleanup_forwards(adb_path, forwards)


def capture_android_state():
    adb_path = find_adb()
    ensure_single_device(adb_path)
    pids = get_package_pids(adb_path)
    if not pids:
        raise RuntimeError("没有找到校园 App 进程。请先打开校园 App 后再试。")

    _, page, forwards = find_target_page(adb_path, pids)
    try:
        current_url, scene, cookies, cookie_meta, local_storage, session_storage, user_agent = capture_auth_and_scene(page)
        return {
            "user_agent": user_agent,
            "page": page,
            "page_url": current_url,
            "scene": scene,
            "cookies": cookies,
            "cookie_meta": cookie_meta,
            "local_storage": local_storage,
            "session_storage": session_storage,
        }
    finally:
        cleanup_forwards(adb_path, forwards)
