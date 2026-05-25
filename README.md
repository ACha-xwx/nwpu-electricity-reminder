# NWPU-electricity-reminder

> 给西北工业大学学生用的宿舍电量查询和提醒工具。支持网页登录状态抓取、低电量提醒和可选 Qmsg 推送。

这个工具主要做三件事：

- 查询宿舍当前剩余电量
- 电量低于阈值时提醒
- 按需推送到 `Qmsg`

## 先看结论

顺序很简单：

1. 先运行 `capture_web_session.py` 抓一次登录状态
2. 再运行 `check_electricity.py` 或 `check_electricity_linux.py` 查询余额
3. 跑通后再去配 `Qmsg` 和定时任务

浏览器路线一直不通的话，在 GitHub 上提 issue 就行。

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

1. 启动一个 Chrome / Edge 窗口
2. 进入移动服务平台首页
3. 等你手动完成登录和进入电费页面
4. 在页面会话信息出现后生成 `check_electricity.json`
5. 顺手刷新一份本地浏览器会话缓存，给后续查询兜底

这份浏览器会话缓存不会放在仓库目录里。Windows 下默认保存在：

`C:\Users\你的用户名\AppData\Local\nwpu-electricity-reminder`

`check_electricity.json` 里会保存网页登录状态，后面也可能写入 Qmsg Key。这个文件不要上传到 GitHub，也不要发给别人。仓库里的 `.gitignore` 已经默认忽略它。

请按这个顺序手动操作：

1. 点击页面上方的“请登录”按钮
2. 在新页面底部点击“更多登录方式”，再选择“统一身份认证”
3. 看不到底部入口时，直接点击页面右上角的蓝色“统一身份认证入口”按钮
4. 进入统一身份认证后，脚本会自动切成电脑端窗口，请正常登录
5. 遇到“安全验证”弹窗时，按页面提示完成短信或邮箱验证
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

Qmsg 网页端步骤：

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

打开就行。

`mode` 常见有两种：

- `private`：发给个人 QQ
- `group`：发到群

官方公共版更适合私聊。要发群消息，需要自己准备机器人或自建方案。

## 常用文件

- `capture_web_session.py`：抓浏览器会话
- `capture_web_session_windows.bat`：Windows 双击抓浏览器会话
- `check_electricity.py`：Windows 查询与提醒
- `check_electricity_linux.py`：Linux / 服务器查询
- `run_check_windows.bat`：Windows 双击执行查询
- `run_check_windows_silent.vbs`：Windows 静默执行查询
- `retry_pending_notifications.py`：补发之前没发出去的 Qmsg 消息
- `run_retry_pending.sh`：Linux / 服务器定时补发入口
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
0 8,20 * * * cd /path/to/nwpu-electricity-reminder && /usr/bin/python3 check_electricity_linux.py >> cron.log 2>&1
*/5 * * * * cd /path/to/nwpu-electricity-reminder && /usr/bin/python3 retry_pending_notifications.py >> cron.log 2>&1
```

第一行负责每天 8 点和 20 点查询电量。第二行负责补发之前因为 Qmsg 临时故障而没发出去的消息。

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

然后再执行查询脚本。还是不通的话，提 issue。

### 3. 没有服务器还能用吗

能。对大多数同学来说，自己电脑 + 官方 `Qmsg` 私聊就已经够用了。

## 来源说明

原始仓库：

- [qllokirin/npu_check_electricity](https://github.com/qllokirin/npu_check_electricity)

早期参考脚本：

- [cheanus/Automation/NoticeElectricity.py](https://github.com/cheanus/Automation/blob/main/NoticeElectricity.py)

## 最后提醒

先别急着配定时任务。最重要的是先抓到一份可用的登录状态。

推荐顺序：

1. 先抓浏览器会话
2. 先手动查通一次
3. 再加 Qmsg
4. 最后再配定时任务
