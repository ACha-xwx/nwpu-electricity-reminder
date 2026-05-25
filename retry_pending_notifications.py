from check_electricity_linux import send_qmsg, send_qqbot_http
from nwpu_api import get_base_dir
from pending_push import flush_pending_pushes


def send_target(message, push_config):
    provider = push_config.get("provider", "qmsg")
    if provider == "qmsg":
        send_qmsg(message, push_config)
        return
    if provider == "qqbot_http":
        send_qqbot_http(message, push_config)
        return
    raise ValueError(f"不支持的补发渠道：{provider}")


def main():
    base_dir = get_base_dir()
    result = flush_pending_pushes(base_dir, send_target)

    if result["delivered"]:
        print(f"补发成功 {result['delivered']} 条。")
    if result["dropped"]:
        print(f"已丢弃过期或重试过多的待补发消息 {result['dropped']} 条。")
    if result["remaining"]:
        print(f"仍有 {result['remaining']} 条待补发消息保留在 {result['path']}。")


if __name__ == "__main__":
    main()
