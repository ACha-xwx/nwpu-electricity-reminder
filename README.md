# nwpu-electricity-reminder

> A dorm electricity reminder tool for NWPU students, with Android session capture, low-balance alerts, and optional Qmsg push.

给西工大学生用的宿舍电量提醒小工具，支持安卓校园 App 登录状态抓取、低电量提醒，以及可选的 `Qmsg` 推送。

## 仓库简介

如果你想填写 GitHub 仓库简介，推荐直接用这一句：

`A dorm electricity reminder tool for NWPU students, with Android session capture, low-balance alerts, and optional Qmsg push.`

它能做的事很简单：

- 查宿舍当前剩余电量
- 电量低于阈值时提醒你
- 如果你愿意，还能发私聊消息或群消息

## 先看结论

如果你只是想自己用，最推荐这条路：

1. 用安卓手机打开校园 App 的“宿舍电费 / 用量查询”页面
2. 电脑运行 `capture_android_session.py` 抓一次登录状态
3. 再运行 `check_electricity.py` 或 `check_electricity_linux.py`
4. 想收私聊提醒的话，接官方 `Qmsg` 就够了，不一定要自己搭 QQ 机器人

也就是说：

- **没有服务器，也能用**
- **不会写代码，也能照着做**
- **大多数同学不需要群推送**

## 这个项目现在为什么要先连一下安卓手机

因为学校接口现在经常会拦脚本直连，常见现象就是返回 `HTTP 412`。

这不代表项目不能用，只是说明：

- 直接拿最原始的 Python 请求去查，容易被拦
- 先从安卓校园 App 抓一次当前登录状态，会稳很多
- 抓完以后，电脑或服务器通常可以直接查
- 等登录状态过期了，再重新抓一次就行

你可以把它理解成：

“手机负责帮你拿到一次合法的登录状态，之后脚本拿着这份状态继续查。”

## 适合哪几种同学

### 1. 只想低电量时提醒一下自己

最省心。

- 不需要服务器
- 不需要群推送
- 不需要自己搭 QQ 机器人

直接用：

- `capture_android_session.py`
- `check_electricity.py`
- 官方 `Qmsg` 私聊推送

其中 `check_electricity.py` 现在已经同时支持：

- Windows 弹窗提醒
- 按配置发送 `Qmsg` 或本地 QQ 机器人消息

### 2. 想每天固定播报一次或两次

也可以。

- 有服务器：用 `check_electricity_linux.py` + `cron`
- 没服务器：用自己电脑的计划任务

如果你想“每次检查都发一条当前电量”，把配置里的 `report_every_check` 改成 `true`。

### 3. 想发到群里

这属于进阶玩法。

一般要你自己已经有：

- QQ 机器人
- 或者捐赠版 / 私有部署的 Qmsg

如果你只是自己收消息，真的没必要先折腾群推送。

补一句现在的实际情况：

- 官方公共版更适合私聊提醒
- 如果你想发群，一般要自己搭捐赠版或私有云

## 最快上手

这一节最适合第一次用的人。

如果你不想看太多原理，直接按下面做就行。

### 第 0 步：先把项目放到一个固定目录

例如：

- Windows：`D:\Projects\npu_check_electricity`
- Linux：`/home/你的用户名/npu_check_electricity`

后面所有命令，都默认你已经进入这个项目目录。

Windows 可以先打开终端，再执行：

```powershell
cd /d D:\你的目录\npu_check_electricity
```

Linux 可以执行：

```bash
cd /path/to/npu_check_electricity
```

### 第 1 步：准备环境

你需要：

- 一台 Windows 电脑，或者一台 Linux 服务器
- 一个安卓手机
- 手机里已经登录校园 App
- 一根数据线
- 电脑装好 Python 3.10 及以上
- 电脑能识别 `adb`

#### 1.1 先确认 Python 能用

Windows 推荐执行：

```powershell
py -3 --version
```

如果没有 `py`，再试：

```powershell
python --version
```

Linux 直接试：

```bash
python3 --version
```

只要看到 `Python 3.10` 或更高版本就可以。

如果这里就报“找不到命令”，先装 Python，再继续下面步骤。

#### 1.2 再确认 `adb` 能用

在终端里执行：

```powershell
adb devices
```

或者如果你的 `adb` 不在环境变量里，就用完整路径执行。

第一次连手机时，手机上通常会弹出：

- “是否允许 USB 调试”

这时记得点“允许”。

如果 `adb devices` 能看到一台设备，就说明这一步通过了。

手机这边记得：

- 打开开发者选项
- 打开 `USB 调试`
- 进入校园 App 的“宿舍电费 / 用量查询”页面

#### 1.3 最容易漏掉的手机步骤

这一步非常关键，很多人卡住就是因为漏了这里：

1. 手机一定要先打开校园 App
2. 一定要点进“宿舍电费 / 用量查询”那个页面
3. 不要只停留在首页，也不要停在缴费记录页

如果页面没打开对，`capture_android_session.py` 很可能会提示找不到目标页面。

### 第 2 步：安装依赖

先确保你已经在项目目录里，再执行：

```bash
pip install -r requirements.txt
```

如果你的环境里 `pip` 对应的不是 Python 3，也可以这样写：

```powershell
py -3 -m pip install -r requirements.txt
```

或者：

```bash
python3 -m pip install -r requirements.txt
```

看到依赖安装完成，就可以继续下一步。

### 第 3 步：抓一次登录状态

先确认这三个条件都满足：

1. 手机已经连上电脑
2. `adb devices` 能看到手机
3. 手机里已经打开校园 App 的“宿舍电费 / 用量查询”页面

然后执行：

```bash
python capture_android_session.py
```

如果你在 Windows 上更稳妥一点，可以这样执行：

```powershell
py -3 capture_android_session.py
```

如果一切正常，你会得到一个 `check_electricity.json`。  
这个文件默认就在项目目录里。

这个文件里会保存：

- 你的宿舍信息
- 当前登录状态
- 当前页面的 `Cookie`
- 当前页面的 `User-Agent`

正常情况下，终端里还会看到类似这些提示：

- “配置文件已写入”
- “识别到的宿舍：xxx”
- “登录信息已更新”

如果这里失败了，先优先排查这三件事：

1. 手机有没有真的打开到正确页面
2. USB 调试有没有授权成功
3. `adb devices` 能不能看到手机

### 第 3.5 步：如果你想先看看配置文件长什么样

可以参考：

- `check_electricity.example.json`

真正运行时脚本读的是你自己的：

- `check_electricity.json`

一般来说：

- `example` 是模板
- `json` 是你自己的真实配置

后者里会带登录状态，所以不要随便发给别人。

### 第 4 步：先手动查一次

如果你在 Windows 上想要弹窗提醒，或者想顺手测试 `Qmsg` 配置：

```bash
python check_electricity.py
```

如果你不想自己敲命令，也可以直接双击：

- `run_check_windows.bat`：带窗口运行，适合第一次测试
- `run_check_windows_silent.vbs`：静默运行，适合放到开机自启

这个脚本现在的行为是：

- 低于阈值时：弹窗提醒，同时按配置发送消息
- 没低于阈值但 `report_every_check=true` 时：不弹窗，但会发送一条常规播报
- 如果登录状态看起来已经失效：会提示你重新运行 `capture_android_session.py`，并在已配置推送时发一条提醒消息

如果你是在服务器上，或者只是想看命令行输出：

```bash
python check_electricity_linux.py
```

这一步建议你先别急着配定时任务，先手动跑通一次。

跑通之后你通常会看到：

- 当前时间
- 当前剩余电量
- 宿舍信息

如果你已经配好了 `Qmsg`，还可能看到：

- “推送成功，第 1 个渠道（qmsg）”

如果这里就失败，优先不要先折腾定时任务，先把这一步跑通。

### 第 5 步：需要时再加推送

大多数同学建议直接用官方 `Qmsg` 私聊。

把 `check_electricity.json` 里的 `push` 改成下面这样：

```json
{
    "provider": "qmsg",
    "key": "你的QmsgKey",
    "mode": "private",
    "qq": "接收消息的QQ号"
}
```

说明：

- `provider` 固定写 `qmsg`
- `mode` 写 `private` 表示私聊
- `qq` 写接收消息的 QQ 号

如果你只是自己收提醒，到这里就已经够用了。

改完配置后，记得再手动运行一次查询脚本，确认消息真的能发到你的 QQ。

无论你运行的是：

- `check_electricity.py`
- `check_electricity_linux.py`

只要配置里有 `push`，它们现在都会按配置发消息。

### 第 6 步：Qmsg 网页端怎么配

如果你是第一次接触 `Qmsg`，一般还要做一下网页端配置。

按官方说明，私聊推送的大致流程是：

1. 打开 [Qmsg 开始页](https://qmsg.zendee.cn/docs/start/) 或 [Qmsg 管理台](https://qmsg.zendee.cn/user)
2. 登录后，先选一个你准备用的机器人
3. 在管理台里添加“接收消息的 QQ 号”
4. 用你的 QQ 去把这个机器人加为好友
5. 在管理台里找到你自己的 `Key`
6. 把这个 `Key` 和你的 QQ 号填回 `check_electricity.json`

你可以把它理解成：

- 管理台负责“告诉 Qmsg 你想让谁收消息”
- 配置文件负责“告诉脚本发消息时该用哪个 key、发给谁”

如果你已经填好了 `key`，但是还是收不到消息，最常见的原因就是：

1. 还没在管理台添加接收 QQ
2. 你的 QQ 还没加那个机器人好友
3. `check_electricity.json` 里的 `qq` 号填错了
4. `key` 填错了

Qmsg 的接口格式和参数说明可以看官方文档：

- [Qmsg 开始页](https://qmsg.zendee.cn/docs/start/)
- [Qmsg API 文档](https://qmsg.zendee.cn/docs/api/)

## 配置文件怎么理解

项目会用到一个 `check_electricity.json`。

你可以参考仓库里的：

- `check_electricity.example.json`

最常见的几个字段如下：

### `warning_electric`

低于这个值就提醒。

比如：

```json
"warning_electric": 10
```

表示剩余电量低于 `10` 时提醒。

### `report_every_check`

这个字段决定“每次检查时要不要顺便播报当前电量”。

- `false`：只在低于阈值时提醒
- `true`：每次运行都发一条当前电量

如果你想做“每天早上 8 点和晚上 8 点各播报一次”，这个字段一般要设成：

```json
"report_every_check": true
```

### `auth`

这里保存的是从安卓校园 App 抓到的登录状态。

一般不需要手改。

如果后面脚本突然又查不了了，最常见的原因就是这部分过期了。  
这时重新运行一次：

```bash
python capture_android_session.py
```

通常就能恢复。

现在两个查询脚本都会尽量帮你兜一下：

- `check_electricity.py`
- `check_electricity_linux.py`

如果它们判断这次失败很像“登录状态过期”，并且你已经配好了 `push`，就会主动发一条提醒你刷新登录状态。

### `push`

这是推送配置。

最推荐的私聊例子：

```json
"push": {
    "provider": "qmsg",
    "key": "你的QmsgKey",
    "mode": "private",
    "qq": "你的QQ号"
}
```

如果你已经有自己的群机器人，也可以改成群推送，但这不是大多数同学的必需项。

## 如果你想手动重新选宿舍

有时候抓登录状态时，宿舍信息没有自动带全，或者你后来换宿舍了，可以再跑一次：

```bash
python bind_room.py
```

它会让你手动选择：

- 校区
- 楼栋
- 房间

然后把新的宿舍信息写回配置文件。

## 定时运行怎么做

### 方案 A：没有服务器

直接用自己的电脑也可以。

最简单的思路：

- Windows 计划任务
- 或者开机自动运行

如果你只想低电量时提醒自己，这已经够用了。

如果你是 Windows 用户，最省事的做法是：

1. 先双击一次 `run_check_windows.bat`，确认能正常查询
2. 想静默运行的话，用 `run_check_windows_silent.vbs`
3. 把 `run_check_windows_silent.vbs` 的快捷方式放进启动文件夹，或者用计划任务调用它

启动文件夹可以在资源管理器地址栏输入：

```text
shell:startup
```

这样以后开机就会自动检查一次。

如果你想改成“每天固定几点运行”，比起开机自启，更推荐用 Windows 计划任务。

### 方案 B：有服务器

服务器上推荐用：

```bash
python check_electricity_linux.py
```

然后配 `cron`。

比如你想每天北京时间早上 `08:00` 和晚上 `20:00` 各查一次：

```cron
CRON_TZ=Asia/Shanghai
0 8,20 * * * cd /path/to/npu_check_electricity && /usr/bin/python3 check_electricity_linux.py >> cron.log 2>&1
```

如果你想“固定时间播报当前电量”，记得把：

```json
"report_every_check": true
```

打开。

如果你只想低电量才提醒，就保持 `false`。

## 出发前自检清单

如果你准备把这份 README 发给同学，建议他们在真正开始前先自检一遍：

1. 能不能在终端里看到 Python 版本
2. `adb devices` 能不能看到手机
3. 手机是否已经打开到校园 App 的“宿舍电费 / 用量查询”页面
4. 是否已经运行过 `capture_android_session.py`
5. 项目目录里是否已经生成了 `check_electricity.json`
6. 如果要私聊提醒，是否已经在 Qmsg 管理台添加接收 QQ 并加了机器人好友
7. 是否已经手动跑通过一次 `check_electricity.py` 或 `check_electricity_linux.py`

## 常见问题

### 1. 运行时提示 `412 Precondition Failed`

这是目前最常见的问题。

通常说明学校接口把你的直连请求拦了。

先别急着怀疑代码，按这个顺序排查：

1. 先确认你刚刚在安卓手机里打开过正确的电费页面
2. 重新运行一次 `python capture_android_session.py`
3. 再运行查询脚本

如果还是不行：

- 电脑网络环境可能也有影响
- 服务器出口 IP 也可能有影响

### 2. 之前能查，后来突然不能查了

大概率是登录状态过期了。

重新运行：

```bash
python capture_android_session.py
```

通常就能恢复。

如果你已经配置了 `Qmsg` 或别的推送渠道，现在脚本也会尽量给你补发一条：

“登录状态可能已过期，请重新抓取会话”

### 3. 我没有服务器，还值得用吗

值得。

对大多数人来说，最实用的就是：

- 平时不管它
- 电量低了给自己发私聊

这完全不需要服务器。

### 4. 我能不能把这套东西借给同学一起用

理论上可以，但分两种情况。

#### 借“推送通道”

可行，而且更推荐。

意思是：

- 同学们各自查自己的电量
- 只是消息借你的渠道发

但其实对大多数同学来说，直接各自用官方 `Qmsg` 私聊就已经够了。

#### 借“服务器帮别人代查”

也能做，但不太建议公开大规模用。

原因很现实：

- 每个人都要把自己的登录状态交给服务器
- 这些数据本质上是代查凭证
- 人一多，更容易触发学校接口风控

所以如果只是少量熟人互相帮忙，还能接受；如果想做成面向很多人的公共服务，就没那么稳了。

## 推荐的实际使用方式

如果你问我最推荐哪一种，我会这样排：

### 最推荐：自己电脑 + 官方 Qmsg 私聊

优点：

- 门槛最低
- 不需要服务器
- 不需要 QQ 机器人
- 最适合大多数同学

### 第二推荐：自己的服务器 + 定时查询

优点：

- 不用开自己电脑
- 适合固定时间播报
- 适合长期运行

### 最后再考虑：群推送 / 多人共用

这条路不是不能走，只是维护成本更高。

## 文件说明

仓库里最常用的几个文件：

- `capture_android_session.py`：抓安卓校园 App 的登录状态
- `bind_room.py`：手动重新选宿舍
- `check_electricity.py`：Windows 弹窗提醒版，也支持按配置推送消息
- `check_electricity_linux.py`：服务器 / 命令行版
- `check_electricit_linux.py`：旧文件名兼容入口，已有计划任务暂时不用急着改
- `run_check_windows.bat`：Windows 双击运行版
- `run_check_windows_silent.vbs`：Windows 静默运行版
- `check_electricity.example.json`：示例配置
- `check_electricity.json`：你自己实际在用的配置文件

其中：

- `check_electricity.json` 默认不会提交到 Git
- 因为里面有你的登录状态和推送配置

## 来源说明

这个项目最初是从下面这个仓库开始的：

- [qllokirin/npu_check_electricity](https://github.com/qllokirin/npu_check_electricity)

现在这份版本是在原项目基础上，结合当前学校接口情况，继续补出来的一版，主要新增了这些能力：

- 安卓校园 App 登录状态抓取
- `412` 场景下的浏览器 / 安卓回退
- Windows 弹窗提醒和消息推送并存
- `Qmsg` 私聊 / 群推送支持
- 更适合同学直接照着跑的 README 和启动脚本

更早的思路也参考过这个脚本：

- [cheanus/Automation/NoticeElectricity.py](https://github.com/cheanus/Automation/blob/main/NoticeElectricity.py)

## 最后提醒

这个项目现在最关键的一点不是“代码写得多复杂”，而是：

**先从安卓校园 App 抓到一份可用的登录状态。**

这一步通了，后面大多数事情都好办。  
这一步没通，再怎么改阈值、改定时、改推送，都会不稳。

如果你只是想最快落地：

1. 先抓登录状态
2. 先手动查一次
3. 再加私聊推送
4. 最后才考虑定时和群推送
