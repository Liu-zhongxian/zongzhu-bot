# 任务说明书：从四个参考仓库借鉴的改进

创建：2026-10-21（Asia/Shanghai）。状态：**第 1、2 项已实现，2026-10-21 微雪 1.75C 实机简单测试通过**；提交失败路径与 Mac 重启自启尚未实测。其余为候选，未开始。

## 1. 来源

2026-10-21 对比了四个仓库（均为 `main` 分支当日版本，只借鉴思路，没有复制代码）：

| 仓库 | 是什么 | 和本项目的关系 |
| --- | --- | --- |
| [JosssphZhou/groki-bot](https://github.com/JosssphZhou/groki-bot) | M5Stack CoreS3 桌面机器人，语音对接 Grok Bot | 目标相同（语音给 Grok Bot 派任务） |
| [justhalfbit/xiaozhi-hub-server](https://github.com/justhalfbit/xiaozhi-hub-server) | 基于同一上游 xiaozhi-esp32-server，按称呼分派给 Claude Code / 各家大模型 | 后端基础相同 |
| [ananhq/anan-iphone-use](https://github.com/ananhq/anan-iphone-use) | M5 StopWatch 当 MCP 服务端，用 USB/BLE 键鼠操作 iPhone | 同为 CO5300 屏幕，眼睛同样源自 m5stack-stopwatch-avatar |
| [onehumanbeing/esp32-iphone-agent](https://github.com/onehumanbeing/esp32-iphone-agent) | ESP32 接收 AirPlay、模拟 HID，iPhone App 跑 Agent | 设备诊断与协议设计可参考 |

## 2. 任务清单

| # | 任务 | 来源 | 改动量 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 提交回执即时出声：固定短句音频缓存 + 先播报后提交 | hub-server 设计文档第 9 节 | 小 | **完成，实机通过** |
| 2 | 后端开机自启 + 健康检查 + 防休眠 | hub-server `scripts/autostart.sh` | 小 | **完成，Mac 重启后自启待实测** |
| 2b | 本机 OTA 不可用时，固件不再回退旧官方 MQTT | 本项目任务记录第 17 节 | 中（要刷固件） | 未开始 |
| 3 | 用 `gbot` 命令行读 Bot 对话，流式回传第一句（替换"Bot 写回复文件"） | groki-bot `gbot_http_proxy.py` | 中 | 未开始，需先确认账号能用 `grok-bot-cli` |
| 4 | 闲聊用快速模型答，耗时任务才交给 Bot | groki-bot 分流规则、hub-server 呼名路由 | 中 | 未开始，需用户定规则 |
| 5 | ASR 热词 + 识别后纠错表；评估 X-ASR 降内存；精简安装依赖；句中停顿被切成两句 | hub-server 设计文档第 3、10 节 | 中 | 停顿已处理：2026-10-21 实测 700ms 会把一句话切成两次提交，安装模板改回上游默认 1000ms；其余未开始 |
| 6 | 整理"时间设计一览"（300 秒等待、保活、补送各管什么） | hub-server 设计文档第 6 节 | 小（文档） | 未开始 |
| 7 | 固件上报重启原因、堆内存、运行时长 | esp32-iphone-agent `status` 心跳 | 中（要刷固件） | 未开始 |
| 8 | 主机渲染眼睛预览；配网页二维码；升级保留 NVS 的检查脚本；屏幕验证码绑定设备 | anan-iphone-use `tools/` 与配对流程 | 各自中等 | 未开始 |
| 9 | 文档拆分（设计 / 使用 / 历史）；仓库 AGENTS.md；Bot 指令文字移到单独文件 | hub-server、anan、esp32-iphone-agent | 小 | 未开始 |

不做：人脸追踪与舵机（板子没有）、Grok Bot 原生语音内部接口（依赖 App 版本）、完整管理后台。

## 3. 第 1 项：提交回执即时出声

**问题。** 说完话后要等 Webhook 返回才合成并播报"任务已提交"，实测约 3 秒（任务记录第 15.2 节）。其中 EdgeTTS 联网合成约 2 秒，Webhook 约 1–3 秒。

**做法。**

- 新增 `core/handle/grokBotPhrases.py`：固定短句（"好的，正在交给 Bot。""我在。"）合成一次后，音频按 TTS 类型、音色、采样率、文字缓存在内存。板子连上后在后台预先合成，之后直接发出缓存的 Opus 包，不走 TTS 队列。
- `grokBotHandle.py` 拆成两段：先做检查（空指令、过长、配置、去重、回传目录），不通过就直接播报原因，不提交；通过后**同时**播报回执和发 Webhook。
- Webhook 成功：不再说第二句，屏幕进入等待秒数。失败（4xx）：先让屏幕退出等待，再播报"任务未提交"的原因。结果不确定（超时、返回格式不对）：播报原有的"暂时无法确认……"，保留等待。
- 缓存还没就绪时（服务刚启动、合成失败），退回原来的实时合成，行为与以前一致。

**提示语的变化。** 以前成功后说"任务已提交，Bot 回复后会显示在屏幕上"；现在一开口就说"好的，正在交给 Bot"，这时 Webhook 还没返回，所以不说"已提交"。提交失败时会在回执之后补一句失败原因。

## 4. 第 2 项：开机自启与健康检查

**问题。** Mac 重启后后端没有自动启动，板子取 OTA 失败，回退到旧的官方 MQTT（任务记录第 17 节）。

**做法。** 新增 `tools/autostart.sh`（macOS launchd，用户级）和 `tools/launcher.c`：

| 命令 | 作用 |
| --- | --- |
| `enable` | 编译启动器 `~/Applications/ZongzhuBackend.app`，写入 `~/Library/LaunchAgents/com.zongzhu.backend.plist`，登录后自动启动，进程退出后自动拉起；马上启动并等 OTA 接口可访问 |
| `disable` | 停止服务并删除自启文件 |
| `restart` | 重启后台服务（更新代码、改配置后） |
| `status` | 自检：自启是否开启、指向哪份安装；8000/8003 是否在监听；OTA 是否返回；`.config.yaml` 里的 WebSocket 地址是否是本机当前局域网 IP；Webhook 配置是否存在且权限为 600 |

- 后端运行期间启动器同时运行 `caffeinate -i -w <后端进程>`，Mac 不会因为空闲而睡眠（合盖仍会睡眠）；后端退出时它也结束。
- 日志：`logs/backend.stdout.log`、`logs/backend.stderr.log`。
- 一个用户只有一份自启文件；`status` 会提示它是否指向当前目录。

**macOS 隐私权限。** 仓库放在"桌面""文稿""下载"里时，launchd 直接启动的 bash 会被系统静默拒绝（2026-10-21 实测：`start.sh: Operation not permitted`，不弹窗）。所以 launchd 启动的是一个很小的启动器应用"宗主后端"（`tools/launcher.c`，ad-hoc 签名），由它运行 `start.sh`：第一次访问这些目录时系统会弹窗询问，点"允许"即可，以后不再询问。启动器源码不变就不重新编译，已给的授权一直有效。点了"不允许"时，到"系统设置 → 隐私与安全性 → 文件与文件夹 → 宗主后端"打开，再运行 `restart`。

`web/install-mac.sh` 最后让用户在"1) 开机自启"和"2) 手动启动"之间选择，没有默认项，不回答会一直问；没有可交互的终端时按手动处理。选手动的以后随时可以运行 `tools/autostart.sh enable`。已经开着自启时，重复运行（即更新）直接重启后端，不再询问。

## 5. 本机已做的验证（2026-10-21）

- 后端测试 55 项通过（原 46 项 + 新增 8 项短句缓存与提交流程 + 1 项 hello 不带 features 的回归）。
- 自启：在本机（仓库在"桌面"下）`enable` 成功，`status` 7 项正常；`kill -9` 后端进程后 4 秒内自动拉起，`caffeinate` 跟着新进程重新挂上。
- 短句缓存：模拟设备只发 hello（不说话、不提交任务），日志显示两条短句缓存成功，每条合成约 2 秒，即以后省下的时间。
- 顺带修复：板子 hello 不带 `features` 时，等待界面检查每秒报一次 `AttributeError`（`conn.features` 为 `None`）。正式固件总会带 `features`，所以以前没出现过。

实机（2026-10-21 13:40，微雪 1.75C，固件 2.5.2.9，用户确认测试完毕）：板子从自启后端的本机 OTA 取得配置并建立 WebSocket 连接；识别完成的同一秒播出缓存回执"好的，正在交给 Bot。"（以前约 3 秒）；提交后约 16 秒收到 Bot 回传并逐句朗读；全程无报错。

还没做：提交失败路径（第 6 节第 4 步）、Mac 重启后的自启（第 5 步）。

## 6. 验收步骤

后端测试（不连板子）：

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m pytest tests/test_grok_bot.py tests/test_grok_bot_reply.py tests/test_grok_bot_phrases.py -q
```

实机（用户现场）：

1. （本机已完成）停掉前台运行的 `start.sh`，执行 `bash tools/autostart.sh enable`，看到"服务已启动"。如果弹出"宗主后端"想访问文件夹，点"允许"。
2. （本机已完成）`bash tools/autostart.sh status`，各项为"正常"。
3. 说"你好宗主"，再说一个任务。预期：说完后约 1 秒内听到"好的，正在交给 Bot"，随后屏幕显示等待秒数，Bot 回复后照常朗读。
4. 把 Webhook 配置里的 token 临时改错一位，再说一个任务。预期：先听到回执，紧接着听到"Bot 服务拒绝了请求，任务未提交……"，屏幕不停在等待。测完改回。
5. 重启 Mac，登录后不开终端，直接唤醒板子说话。预期：正常连到 Bot 链路，不回到官方小智。

全部通过后提交并推送 GitHub。改动包括 `web/install-mac.sh`，推送后 Pages 会自动重新发布网站。
