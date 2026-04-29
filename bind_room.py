import asyncio

from nwpu_api import (
    create_async_client,
    dump_config,
    extract_remaining_electricity,
    extract_room_info,
    get_config_path,
    load_config_or_empty,
    post_charge_request,
)


async def get_campus(auth):
    data = {"feeitemid": "182", "type": "select", "level": "0"}
    async with create_async_client(auth) as client:
        campus_all = (await post_charge_request(client, data))["data"]

    lines = [f"{index}  {campus['name']}" for index, campus in enumerate(campus_all)]
    lines.append("请选择校区，输入前面的数字后回车。")
    return "\n".join(lines), campus_all


async def get_building(auth, campus):
    data = {"feeitemid": "182", "type": "select", "level": "1", "campus": campus}
    async with create_async_client(auth) as client:
        building_all = (await post_charge_request(client, data))["data"]

    lines = [f"{index}  {building['name']}" for index, building in enumerate(building_all)]
    lines.append("请选择楼栋，输入前面的数字后回车。")
    return "\n".join(lines), building_all


async def get_room(auth, campus, building):
    data = {
        "feeitemid": "182",
        "type": "select",
        "level": "2",
        "campus": campus,
        "building": building,
    }
    async with create_async_client(auth) as client:
        room_all = (await post_charge_request(client, data))["data"]

    lines = [f"{index}  {room['name']}" for index, room in enumerate(room_all)]
    lines.append("请选择房间，输入前面的数字后回车。")
    return "\n".join(lines), room_all


async def get_electric_left(auth, campus, building, room):
    data = {
        "feeitemid": "182",
        "type": "IEC",
        "level": "3",
        "campus": campus,
        "building": building,
        "room": room,
    }
    async with create_async_client(auth) as client:
        result = await post_charge_request(client, data)
    return extract_remaining_electricity(result), extract_room_info(result)


async def wait_for_api(auth, timeout_seconds=120, retry_interval=5):
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    last_error = None

    while True:
        if loop.time() - start_time > timeout_seconds:
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
            last_error = error
            print(f"校园接口访问失败：{error}，{retry_interval} 秒后重试。")
            await asyncio.sleep(retry_interval)


async def main():
    file_path = get_config_path()
    config = load_config_or_empty(file_path)
    auth = config.get("auth")

    if not await wait_for_api(auth):
        return

    if file_path.exists():
        print("检测到已有配置文件，这次会重新绑定宿舍，但会保留之前保存的登录状态和推送配置。")
    else:
        print("还没有配置文件，现在开始绑定宿舍。")

    msg, campus_all = await get_campus(auth)
    print(msg)
    campus = campus_all[int(input("请输入编号：").strip())]["value"]

    msg, building_all = await get_building(auth, campus)
    print(msg)
    building = building_all[int(input("请输入编号：").strip())]["value"]

    msg, room_all = await get_room(auth, campus, building)
    print(msg)
    room = room_all[int(input("请输入编号：").strip())]["value"]

    electric_left, room_info = await get_electric_left(auth, campus, building, room)
    print(f"当前剩余电量：{electric_left}，宿舍信息：{room_info}")

    warning_electric = input("请输入提醒阈值，直接回车默认为 10：").strip()
    warning_electric = 10 if warning_electric == "" else int(warning_electric)

    config.update(
        {
            "campus": campus,
            "building": building,
            "room": room,
            "warning_electric": warning_electric,
            "room_display": room_info,
        }
    )
    dump_config(file_path, config)
    print(f"配置已保存到：{file_path}")


if __name__ == "__main__":
    asyncio.run(main())
