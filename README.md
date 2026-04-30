# NWPU-electricity-reminder

> A dorm electricity reminder tool for NWPU students, with web session capture, low-balance alerts, and optional Qmsg push.

给西工大学生用的宿舍电量提醒小工具。

它主要做三件事：

- 查询宿舍当前剩余电量
- 电量低于阈值时提醒
- 按需推送到 `Qmsg`

## 先看结论

顺序很简单：

1. 先运行 `capture_web_session.py` 抓一次登录状态
2. 再运行 `check_electricity.py` 或 `check_electricity_linux.py` 查询余额
3. 跑通后再去配 `Qmsg` 和定时任务

浏览器路线一直不通的话，直接在 GitHub 上提 issue 就行。

## 最短上手

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

Windows 也可以用：

```powershell
py -3 -m pip install -r requirements.txt
```

README 里像 `python xxx.py`、`py -3 ...` 这样的命令，都是在电脑上的终端里输入。

- Windows：`PowerShell`、`Windows Terminal` 或 `命令提示符`
- macOS / Linux：系统自带的 `Terminal`

不想自己敲命令的话，Windows 可以直接双击仓库里的 `.bat` 文件。

### 2. 先抓登录状态

执行：

```bash
python capture_web_session.py
```

或者在 Windows 上直接双击：

- `capture_web_session_windows.bat`

正常情况下会先弹出一个黑色命令行窗口，然后自动打开浏览器。

脚本会做这些事：

1. 启动一个手机样式的 Chrome / Edge 窗口
2. 进入移动服务平台首页
3. 等你手动完成登录和进入电费页面
4. 在页面会话信息出现后生成 `check_electricity.json`
5. 顺手刷新一份本地浏览器会话缓存，给后续查询兜底

这份浏览器会话缓存不会放在仓库目录里。Windows 下默认保存在：

`C:\Users\你的用户名\AppData\Local\nwpu-electricity-reminder`

请按这个顺序手动操作：

1. 点击页面上方的“请登录”按钮
2. 在新页面底部点击“更多登录方式”
3. 选择“统一身份认证”入口
4. 登录你的西北工业大学账号
5. 登录成功后，回到移动服务平台页面
6. 点击“学生电费”或“宿舍电费 / 用量查询”
7. 进入电费页面后，先不要关浏览器，等脚本继续抓取

长时间停在登录页、首页，或者没有继续输出，基本就说明这次没有抓到页面会话信息。

这时可以这样处理：

1. 确认你已经真的进入了“学生电费”或“宿舍电费 / 用量查询”页面
2. 再等几秒，看脚本会不会继续抓取
3. 还是没反应的话，直接关掉浏览器，重新运行一次 `capture_web_session.py`
4. 连续几次都不通，就提 issue

### 3. 手动查询电费余额

Windows：

```bash
python check_electricity.py
```

或者直接双击：

- `run_check_windows.bat`

Linux / 服务器：

```bash
python check_electricity_linux.py
```

跑通后，你会看到：

- 当前时间
- 当前剩余电量
- 宿舍信息

## Qmsg 怎么配

大多数同学只需要官方 `Qmsg` 私聊就够了。

Qmsg 网页端的大致步骤：

1. 打开 [Qmsg 开始页](https://qmsg.zendee.cn/docs/start/) 或 [Qmsg 管理台](https://qmsg.zendee.cn/user)
2. 选一个机器人
3. 在管理台添加接收消息的 QQ
4. 用你的 QQ 把机器人加为好友
5. 复制 `Key`
6. 把 `Key` 和 QQ 号填回 `check_electricity.json`

在 `check_electricity.json` 里加上：

```json
"push": {
    "provider": "qmsg",
    "key": "你的QmsgKey",
    "mode": "private",
    "qq": "你的QQ号"
}
```

想每次检查都发一条当前电量的话，把：

```json
"report_every_check": true
```

打开即可。

`mode` 常见有两种：

- `private`：发给个人 QQ
- `group`：发到群

官方公共版更适合私聊。需要群消息的话，建议自己准备机器人或自建方案。

## 常用文件

- `capture_web_session.py`：抓浏览器会话
- `capture_web_session_windows.bat`：Windows 双击抓浏览器会话
- `check_electricity.py`：Windows 查询与提醒
- `check_electricity_linux.py`：Linux / 服务器查询
- `check_electricit_linux.py`：旧文件名兼容入口
- `run_check_windows.bat`：Windows 双击执行查询
- `run_check_windows_silent.vbs`：Windows 静默执行查询
- `bind_room.py`：手动重选宿舍
- `check_electricity.example.json`：示例配置

## 定时运行

### Windows

最简单的做法：

1. 先双击 `run_check_windows.bat`，确认能正常查询
2. 再用 Windows 计划任务定时调用它

### Linux / 服务器

示例：

```cron
0 8,20 * * * cd /path/to/npu_check_electricity && /usr/bin/python3 check_electricity_linux.py >> cron.log 2>&1
```

想固定时间播报当前电量的话，记得把：

```json
"report_every_check": true
```

打开。

## 常见问题

### 1. 提示 `412 Precondition Failed`

这通常说明学校接口把直连请求拦了。

先重新运行：

```bash
python capture_web_session.py
```

再重新执行查询脚本。  
还是不通的话，提 issue。

### 2. 之前能查，后来突然不能查了

大概率是登录状态过期了。

重新运行：

```bash
python capture_web_session.py
```

这一步会同时刷新：

- `check_electricity.json` 里的网页会话信息
- 本地浏览器会话缓存

然后再执行查询脚本。  
还是不通的话，提 issue。

### 3. 没有服务器还能用吗

能。对大多数同学来说，自己电脑 + 官方 `Qmsg` 私聊就已经够用了。

## 来源说明

原始仓库：

- [qllokirin/npu_check_electricity](https://github.com/qllokirin/npu_check_electricity)

早期参考脚本：

- [cheanus/Automation/NoticeElectricity.py](https://github.com/cheanus/Automation/blob/main/NoticeElectricity.py)

## 最后提醒

这个项目最关键的不是定时任务，也不是推送，而是**先抓到一份可用的登录状态。**

推荐顺序：

1. 先抓浏览器会话
2. 先手动查通一次
3. 再加 Qmsg
4. 最后再配定时任务
