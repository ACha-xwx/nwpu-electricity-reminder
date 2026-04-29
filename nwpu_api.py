import json
import os
import sys
from pathlib import Path

import httpx

API_URL = "https://yktapp.nwpu.edu.cn/jfdt/charge/feeitem/getThirdData"
DEFAULT_CONFIG_NAME = "check_electricity.json"
DEFAULT_REFERER = "https://yktapp.nwpu.edu.cn/jfdt/#/pays?id=182"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://yktapp.nwpu.edu.cn",
    "Referer": DEFAULT_REFERER,
    "X-Requested-With": "XMLHttpRequest",
}
FALLBACK_ELECTRICITY_KEYS = ("当前剩余电量", "瑜版挸澧犻崜鈺€缍戦悽鐢稿櫤")


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_config_path(base_dir=None):
    if base_dir is None:
        base_dir = get_base_dir()
    custom_path = os.getenv("CHECK_ELECTRICITY_CONFIG")
    if custom_path:
        return Path(custom_path)
    return base_dir / DEFAULT_CONFIG_NAME


def load_config_or_empty(file_path):
    if not file_path.exists():
        return {}
    return json.loads(file_path.read_text(encoding="utf-8"))


def dump_config(file_path, data):
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )


def build_request_headers(auth=None):
    headers = DEFAULT_HEADERS.copy()
    if not auth:
        return headers

    if auth.get("user_agent"):
        headers["User-Agent"] = auth["user_agent"]
    if auth.get("referer"):
        headers["Referer"] = auth["referer"]
    if auth.get("origin"):
        headers["Origin"] = auth["origin"]

    extra_headers = auth.get("headers")
    if isinstance(extra_headers, dict):
        headers.update(extra_headers)
    return headers


def build_request_cookies(auth=None):
    if not auth:
        return {}

    cookies = auth.get("cookies")
    if isinstance(cookies, dict):
        return {
            str(key): str(value)
            for key, value in cookies.items()
            if key and value is not None
        }
    return {}


def create_async_client(auth=None, timeout=15.0):
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=build_request_headers(auth),
        cookies=build_request_cookies(auth),
    )


def create_sync_client(auth=None, timeout=15.0):
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers=build_request_headers(auth),
        cookies=build_request_cookies(auth),
    )


async def post_charge_request(client, data):
    response = await client.post(API_URL, data=data)
    response.raise_for_status()
    payload = response.json()
    if "map" not in payload:
        raise ValueError(f"接口返回格式异常：{payload}")
    return payload["map"]


def extract_remaining_electricity(result_map):
    show_data = result_map.get("showData", {})

    for key in FALLBACK_ELECTRICITY_KEYS:
        if key in show_data:
            return float(show_data[key])

    for key, value in show_data.items():
        if "剩余电量" in key or "缍戦悽鐢稿櫤" in key:
            return float(value)

    raise KeyError(f"没有找到剩余电量字段：{list(show_data.keys())}")


def extract_room_info(result_map):
    room_data = result_map.get("data", {})
    parts = [room_data.get("campus", ""), room_data.get("building", ""), room_data.get("room", "")]
    return " ".join(part for part in parts if part).strip()
