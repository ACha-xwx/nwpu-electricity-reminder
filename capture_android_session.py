from android_session import capture_android_state
from nwpu_api import DEFAULT_REFERER, dump_config, get_config_path, load_config_or_empty


def update_config(config, scene, user_agent, referer, cookies):
    return update_config_with_state(config, scene, user_agent, referer, cookies, [], {}, {})


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


def main():
    android_state = capture_android_state()
    scene = android_state["scene"]
    page = android_state["page"]
    page_url = android_state["page_url"] or page.get("url") or DEFAULT_REFERER

    config_path = get_config_path()
    config = load_config_or_empty(config_path)
    config = update_config_with_state(
        config,
        scene,
        user_agent=android_state["user_agent"],
        referer=page_url,
        cookies=android_state["cookies"],
        cookie_meta=android_state["cookie_meta"],
        local_storage=android_state["local_storage"],
        session_storage=android_state["session_storage"],
    )
    dump_config(config_path, config)

    print(f"配置文件已写入：{config_path}")
    if config.get("room_display"):
        print(f"识别到的宿舍：{config['room_display']}")
    print(f"登录信息已更新，这次一共保存了 {len(android_state['cookies'])} 个 Cookie。")
    print("现在可以直接运行 check_electricit_linux.py 或 check_electricity.py。")


if __name__ == "__main__":
    main()
