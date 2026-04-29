import asyncio
import os
import time
from datetime import datetime

import httpx
import pymsgbox

from browser_session import query_electricity_via_browser
from nwpu_api import (
    create_async_client,
    extract_remaining_electricity,
    extract_room_info,
    get_config_path,
    load_config_or_empty,
    post_charge_request,
)


async def get_electric_left(auth, campus, building, room):
    data = {
        "feeitemid": "182",
        "type": "IEC",
        "level": "3",
        "campus": campus,
        "building": building,
        "room": room,
    }
    try:
        async with create_async_client(auth) as client:
            result = await post_charge_request(client, data)
            return extract_remaining_electricity(result), extract_room_info(result)
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 412:
            raise

        print("直接请求被 412 拦截，尝试用浏览器登录状态继续查询。")
        try:
            return await asyncio.to_thread(
                query_electricity_via_browser,
                auth or {},
                campus,
                building,
                room,
            )
        except Exception as browser_error:
            print(f"浏览器回放失败：{browser_error}")
            raise RuntimeError(f"浏览器会话可能已失效：{browser_error}") from browser_error


async def wait_for_api(auth, timeout_seconds=120, retry_interval=5):
    start_time = time.time()
    last_error = None

    while True:
        if time.time() - start_time > timeout_seconds:
            print(f"等待接口超时，最后一次错误：{last_error}")
            return False

        try:
            async with create_async_client(auth, timeout=10.0) as client:
                await post_charge_request(
                    client,
                    {"feeitemid": "182", "type": "select", "level": "0"},
                )
            print("校园接口连接正常。")
            return True
        except Exception as error:
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 412:
                print("校园接口直连被 412 拦截，但仍可继续走浏览器会话回放。")
                return True

            last_error = error
            print(f"校园接口访问失败：{error}，{retry_interval} 秒后重试。")
            await asyncio.sleep(retry_interval)


def build_alert_message(electric_left, room_info, current_time):
    return (
        "宿舍电量不足，请及时充值。\n"
        f"当前时间：{current_time}\n"
        f"当前剩余电量：{electric_left}\n"
        f"宿舍信息：{room_info}"
    )


def build_status_message(electric_left, room_info, current_time):
    return (
        "宿舍电量播报\n"
        f"当前时间：{current_time}\n"
        f"当前剩余电量：{electric_left}\n"
        f"宿舍信息：{room_info}"
    )


def build_auth_expired_message(room_info, current_time, error):
    return (
        "宿舍电量查询失败，登录状态可能已过期。\n"
        f"当前时间：{current_time}\n"
        f"宿舍信息：{room_info}\n"
        "请重新运行 capture_web_session.py 刷新登录状态。\n"
        "浏览器路线还是不通的话，请提 issue 反馈。\n"
        f"可能原因：{summarize_auth_expired_error(error)}"
    )


def should_report_every_check(config):
    return bool(config.get("report_every_check"))


def iter_error_chain(error):
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)


def is_probable_auth_expired(error):
    keywords = (
        "登录",
        "登录态",
        "会话",
        "token",
        "cookie",
        "unauthorized",
        "forbidden",
        "sign in",
        "login",
        "cas",
        "sso",
        "统一身份认证",
        "接口返回格式异常",
        "expecting value",
    )

    for exc in iter_error_chain(error):
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            if exc.response.status_code in {401, 403}:
                return True

            response_preview = exc.response.text[:500].lower()
            if any(keyword in response_preview for keyword in ("login", "cas", "sso", "unauthorized")):
                return True

        message = str(exc).lower()
        if any(keyword in message for keyword in keywords):
            return True

    return False


def summarize_auth_expired_error(error):
    for exc in iter_error_chain(error):
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                return f"接口返回 {status_code}，通常表示登录状态已失效。"
            if status_code == 412:
                return "直连接口被 412 拦截，浏览器登录状态也没能继续完成查询。"

        message = str(exc)
        lower_message = message.lower()
        if "浏览器会话可能已失效" in message:
            return "浏览器登录状态可能已失效。"
        if any(keyword in lower_message for keyword in ("cookie", "token", "login", "unauthorized", "forbidden", "cas", "sso")):
            return "当前保存的登录 Cookie / Token 可能已经失效。"
        if any(keyword in message for keyword in ("登录", "登录态", "会话", "统一身份认证")):
            return "当前保存的登录状态可能已经失效。"

    return "这次失败看起来很像登录状态失效，建议重新抓取一次会话。"


def build_push_targets(config):
    push_targets = []
    push_config = config.get("push")
    if isinstance(push_config, dict):
        push_targets.append(push_config)
    elif isinstance(push_config, list):
        push_targets.extend(item for item in push_config if isinstance(item, dict))

    if "user_id" in config:
        push_targets.append(
            {
                "provider": "qqbot_http",
                "mode": "private",
                "target": str(config["user_id"]),
            }
        )
    if "group_id" in config:
        push_targets.append(
            {
                "provider": "qqbot_http",
                "mode": "group",
                "target": str(config["group_id"]),
            }
        )

    if not push_targets and os.getenv("QMSG_KEY"):
        push_targets.append(
            {
                "provider": "qmsg",
                "key": os.getenv("QMSG_KEY"),
                "mode": os.getenv("QMSG_MODE", "private"),
                "qq": os.getenv("QMSG_QQ"),
            }
        )

    return push_targets


def send_qmsg(message, push_config):
    key = push_config.get("key")
    if not key:
        raise ValueError("Qmsg 推送缺少 key。")

    mode = push_config.get("mode", "private")
    endpoint = {"private": "send", "group": "group"}.get(mode)
    if endpoint is None:
        raise ValueError("Qmsg 的 mode 只能是 private 或 group。")

    data = {"msg": message}
    if push_config.get("qq"):
        data["qq"] = str(push_config["qq"])

    response = httpx.post(
        f"https://qmsg.zendee.cn/{endpoint}/{key}",
        data=data,
        timeout=15.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("success"):
        raise RuntimeError(result.get("reason", "Qmsg 推送失败。"))


def send_qqbot_http(message, push_config):
    mode = push_config.get("mode", "private")
    target = push_config.get("target")
    if not target:
        raise ValueError("本地 QQ 机器人推送缺少 target。")

    base_url = push_config.get("api_base", "http://127.0.0.1:3000").rstrip("/")
    if mode == "private":
        endpoint = "send_private_msg"
        body = {
            "user_id": target,
            "message": [{"type": "text", "data": {"text": message}}],
        }
    elif mode == "group":
        endpoint = "send_group_msg"
        body = {
            "group_id": target,
            "message": [{"type": "text", "data": {"text": message}}],
        }
    else:
        raise ValueError("本地 QQ 机器人推送的 mode 只能是 private 或 group。")

    headers = {"Content-Type": "application/json"}
    if push_config.get("authorization"):
        headers["Authorization"] = push_config["authorization"]

    response = httpx.post(
        f"{base_url}/{endpoint}",
        headers=headers,
        json=body,
        timeout=15.0,
        follow_redirects=True,
    )
    response.raise_for_status()


def send_notifications(message, config):
    push_targets = build_push_targets(config)
    if not push_targets:
        print("没有配置推送渠道，这次只查询，不发送消息。")
        return

    for index, push_config in enumerate(push_targets, start=1):
        provider = push_config.get("provider", "qmsg")
        try:
            if provider == "qmsg":
                send_qmsg(message, push_config)
            elif provider == "qqbot_http":
                send_qqbot_http(message, push_config)
            else:
                raise ValueError(f"不支持的推送渠道：{provider}")
            print(f"推送成功，第 {index} 个渠道（{provider}）。")
        except Exception as exc:
            print(f"推送失败，第 {index} 个渠道（{provider}）：{exc}")


async def main():
    file_path = get_config_path()
    config = load_config_or_empty(file_path)
    auth = config.get("auth")
    room_info_hint = config.get("room_display") or f"{config.get('campus', '-')} {config.get('building', '-')} {config.get('room', '-')}"

    try:
        if not await wait_for_api(auth):
            return

        if not file_path.exists():
            message = "没有找到配置文件，请先运行 capture_web_session.py。"
            print(message)
            pymsgbox.alert(message, "提示")
            return

        print(f"正在读取配置文件：{file_path}")
        electric_left, room_info = await get_electric_left(
            auth,
            config["campus"],
            config["building"],
            config["room"],
        )

        room_info = room_info or config.get("room_display") or f"{config['campus']} {config['building']} {config['room']}"
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        warning_electric = float(config["warning_electric"])

        print(f"当前时间：{current_time}")
        print(f"当前剩余电量：{electric_left}，宿舍信息：{room_info}")

        if electric_left < warning_electric:
            print("电量不足，请及时充值。")
            pymsgbox.alert(
                f"当前剩余电量：{electric_left}\n宿舍信息：{room_info}\n请及时充值。",
                "电量提醒",
            )
            send_notifications(build_alert_message(electric_left, room_info, current_time), config)
        elif should_report_every_check(config):
            print("电量充足，发送常规播报。")
            send_notifications(build_status_message(electric_left, room_info, current_time), config)
        else:
            print("电量充足，这次不发送消息。")
    except Exception as error:
        if is_probable_auth_expired(error):
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = build_auth_expired_message(room_info_hint, current_time, error)
            print(message)
            pymsgbox.alert(
                "登录状态可能已过期，请重新运行 capture_web_session.py 刷新登录状态。",
                "登录状态提醒",
            )
            send_notifications(message, config)
            return
        raise


if __name__ == "__main__":
    asyncio.run(main())
