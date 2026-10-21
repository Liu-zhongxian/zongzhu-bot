# 任务说明书：从四个参考仓库借鉴的改进

创建：2026-10-21（Asia/Shanghai）。状态：**第 1、2 项已实现；第 5 项本机已换 X-ASR（2026-10-22），2026-10-21 微雪 1.75C 实机简单测试通过**；提交失败路径与 Mac 重启自启尚未实测。其余为候选，未开始。

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
| 5 | ASR 热词 + 识别后纠错表；评估 X-ASR 降内存；精简安装依赖；句中停顿被切成两句 | hub-server 设计文档第 3、10 节 | 中 | **本机已换成 X-ASR，加了热词和纠错（2026-10-22，见第 7 节）**；停顿已处理（700ms → 上游默认 1000ms）；安装脚本仍装 FunASR，未改；实机说话已通过 |
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

## 7. 第 5 项：换成 X-ASR，加热词和纠错（2026-10-22）

**改动。**

- `core/providers/asr/sherpa_onnx_local.py`：新增 `model_type: transducer`，加载 X-ASR（sherpa-onnx int8 版，约 174MB）；有热词时用 `modified_beam_search` 给热词加分，`bpe.vocab` 不存在时从 `bpe.model` 导出。切词方式用 `bpe`：这个模型的词表不收单个汉字，用 `cjkchar+bpe` 时中文热词（宗主）会编码失败被跳过。modelscope 改为用到时才导入。需要 sherpa-onnx 1.13 以上，依赖锁定改为 1.13.8。
- `core/utils/asr_text.py`：识别后先整理（去掉中文标点两边的空格、把 "A C P" 合成 "ACP"），再按纠错表替换。默认纠错表取自 10-15 至 10-21 后端日志里的真实错认（"你好中国 / 中主 / 钟主 / 钟国 / 宗猪 / 中猪公" → "你好宗主"），另加 Grok Bot、Claude Code。配置顶层写 `asr_corrections`、`asr_hotwords` 可整个覆盖默认值。
- `core/providers/asr/base.py`：所有识别（包括 FunASR）都走整理和纠错；日志新增 INFO 级 "识别耗时" 和 "识别纠错: 原文 -> 改后"，以后看日志就能对比。
- `config.yaml` 新增 `SherpaXASR` 条目；本机 `data/.config.yaml` 选用它（改前备份在本机 `backups/config-before-xasr-20261022.yaml`）。
- `tools/asr-bench/`：`make_testset.py` 合成测试音频，`benchmark.py` 用后端同一段识别代码跑错字率、耗时、内存。

**对比方法。** 旧日志只有识别出的文字：耗时是 DEBUG 级没记下，录音识别完即删除，所以没有可复用的 FunASR 旧音频。改用 30 句（来自日志里的真实指令和项目常用词）× 2 种 macOS 音色（婷婷、Eddy）× 干净/加噪声（信噪比 15dB）= 120 段，两种识别跑同一批。当天本机 EdgeTTS 返回 403，所以用 macOS `say` 合成。Eddy 音色读英文很差，错字率绝对值偏高，只看相对差距。

| | FunASR（SenseVoiceSmall） | X-ASR 不加热词 | X-ASR 加热词 |
| --- | --- | --- | --- |
| 错字率（整理+纠错后） | 21.7% | 16.7% | **15.6%** |
| 干净 / 噪声 | 18.4% / 24.9% | 16.2% / 17.2% | 15.0% / 16.2% |
| 整句全对 | 44 / 120 | 59 / 120 | **65 / 120** |
| "宗主"认对 | 25 / 28 | 28 / 28 | 28 / 28 |
| 每句平均耗时 | 0.204 秒 | 0.036 秒 | 0.045 秒 |
| 模型加载 | 2.2 秒 | 0.7 秒 | 0.7 秒 |
| 模型占内存 / 进程峰值 | 约 1650MB / 3046MB | 约 480MB / 624MB | 约 480MB / 624MB |

纠错表套用到旧日志的 40 条 FunASR 结果上：7 条"宗主"错认全部改正，其余 33 条不变。剩下的错误主要是英文词（README、GitHub、Docker、WebSocket 等），用真实录音复测后再决定是否加纠错规则。

结果文件（本机，不上传）：`logs/asr-compare/funasr-baseline.json`、`xasr-nohot.json`、`xasr-hot.json`、`funasr-history-20261015-1021.tsv`。

**还没做。** 用自己的声音在板子上实际说话验收；15–20 句真实录音复测（放进测试目录，照 `manifest.tsv` 格式写正确文字，重跑 `benchmark.py`）；安装脚本改装 X-ASR 并去掉 torch、FunASR（`web/install-mac.sh` 仍下载 SenseVoiceSmall 约 900MB）。

**回退。** `data/.config.yaml` 里把 `selected_module.ASR` 改回 `FunASR` 并重启后端；纠错对 FunASR 同样生效，不想要时写 `asr_corrections: {}`。

### 7.1 实机测试后的两处修复（2026-10-22）

- **连说几段被提交成几个任务。** 实测连着说了三段，提交了三次。原因：等待状态只在"没人说话、板子也没在出声"的空隙里生效，连续说话时一直等不到。改为提交成功（且板子支持等待界面）后马上停止普通收音（`grokBotHandle.py`）；唤醒或按键照旧恢复，被拒绝或收到回复时照旧退出等待。
- **回复朗读偶尔停顿。** EdgeTTS 一句一句串行合成，每句约 2 秒；短句（如"收到"）播完下一句还没好就会停一下。改为处理当前一句时，按同样的断句规则推算后面两句，交给后台线程先合成（`tts/base.py` 的 `PREFETCH_AHEAD`）；推算不中或后台失败时照旧现合成。`tests/test_tts_prefetch.py` 验证每句只合成一次、顺序不变、后两句与第一句同时开始。
- 日志里只去空格的情况不再记为"识别纠错"。
- **实机确认（2026-10-22 06:11，微雪 1.75C，固件 2.5.2.9）**：用户确认提交后接着说话不再被提交、回复朗读不再停顿。日志：一次唤醒只提交一次；9 句回复里前 3 句同时合成好，之后每句约 1 秒，合成一直领先播放。中英混说（GitHub、Claude Code MCP）识别正确，长句识别 0.09–0.16 秒。
