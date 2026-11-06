# 宗主使用与开发详解

中文 | [English](GUIDE.en.md) · [返回 README](../README.md)

首页 README 只放概要。这里是完整说明：功能细节、本机点歌、接入小米音箱、不用网页的手动安装、刷机、Bot 接口、构建、测试和已知限制。

## 功能

**语音 → Bot → 回传**

- 唤醒后说的话直接提交给 Bot，不用加"让机器人"之类的前缀。
- Bot 把回答写进本机回复文件，后端校验后把字幕和 EdgeTTS 语音发回板子。
- 等待时显示秒数，并暂停普通收音。默认最多等 300 秒，超时的任务会保留，不会自动重发。唤醒或按键可以追加内容。
- 按键打断、等超时、或板子待机了，Bot 做完的结果不会丢：板子空闲时、或下次唤醒问候之后会念出来，开头是"<Bot 名字>做完了："。Bot 之后的补充和更正也接着念，开头是"Bot 补充："。超过 24 小时的不再念。
- 长回复会自动滚动，朗读完后保留全文。连接断开期间没送出的回复，下次连上会补发。
- 对话中再说一次"你好宗主"（包括"你好中主""你好宗猪"这类误识别）只会回一句"我在"，不会当成任务提交；"你好宗主，帮我查天气"会去掉唤醒词，只提交"帮我查天气"。

**屏幕表情**

- 13 种实时绘制的眼睛表情，会跟着设备状态和服务端情绪自动切换。
- 眨眼快闭慢睁，偶尔连眨两下；待机、聆听、说话时会随机转一下眼神。
- 眼睛直接用实心形状绘制，每帧只重绘眼睛移动的区域，不用图片序列帧。

<details>
<summary>13 种表情</summary>

待机、聆听、思考、说话、开心（弯弧 ∩）、兴奋、好奇、困惑、生气、惊讶、难过、困倦（眯缝 ∪）、眩晕。

</details>

**字幕模式**：长按 BOOT 键循环切换，设置断电后也会保存。

| 模式 | 显示内容 |
| --- | --- |
| 完整 | 你说的话和 Bot 的全文，长文自动滚动；眼睛缩小 |
| 简洁 | 只显示 Bot 回复的第一句，最多两行；眼睛保持中等大小 |
| 关闭 | 不显示对话文字，眼睛最大 |

配网、激活、升级这类系统提示在任何模式下都会完整显示，等待秒数也照常显示。

**触摸、动作和按键**

<details>
<summary>展开操作表</summary>

| 操作 | 反应 |
| --- | --- |
| 单击 | 开心 |
| 双击 | 惊讶 |
| 长按 | 生气 |
| 按住后拖动 | 眼睛跟着手指 |
| 左右滑 | 切换表情 |
| 上滑 / 下滑 | 惊讶 / 困倦 |
| 倾斜板子 | 视线跟着倾斜方向 |
| 左右用力摇 4 下 | 眩晕，放稳后恢复 |
| BOOT 键短按 | 开始对话；播放中短按会停止播放 |
| BOOT 键长按 | 切换字幕模式 |

反应持续 2–3 秒，之后回到当前状态（聆听、思考、说话等）。这两块板都没有震动马达，所以没有震动反馈（M5Stack StopWatch 有马达，按键也不同，见 [docs/BOARD-STOPWATCH.md](BOARD-STOPWATCH.md)）。微雪 1.75C 闲置后屏幕会变暗省电，碰一下屏幕即恢复；立创板不做省电变暗。

</details>

## 工作原理

![架构图：板子把语音发给电脑后端，后端识别后通过 Webhook 交给 Grok Bot，Bot 把回复写回电脑上的文件，后端合成字幕和语音发回板子](images/architecture.zh-CN.svg)

## 本机点歌（可选）

打开后，放歌、暂停、切歌、调音量这些话在这台电脑上执行，大约 1 秒见效，不经过 Bot；其他话照旧交给 Bot。默认关闭。

### 打开

1. 在仓库根目录运行 `bash tools/local_music_setup.sh`。它会把 [go-music-dl](https://github.com/guohuiyuan/go-music-dl)（搜歌、拿音频）和 [mpv](https://github.com/mpv-player/mpv)（播放）下载到 `local-music/`，核对写死在脚本里的 SHA-256，校验不过就停下。mpv 用官方的独立包，不用 Homebrew 装，因为 `brew install mpv` 会连带装一份 ffmpeg，和后端用的 ffmpeg-full 冲突。
2. 把脚本最后打印的 `local_music` 一节写进 `xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`，`enabled: true`。样例在 `examples/backend.config.yaml`。
3. 重启后端。板子连上时，后端会在后台启动 go-music-dl（端口 18080）和 mpv，并提前合成"好的""已暂停"这些短句；后端退出时两个程序一起关掉。
4. （可选）想听网易云的会员歌曲：打开 `http://localhost:18080/music/setup`，用 `local-music/go-music-dl/service.log` 里的 `Web setup token` 建一个管理员，再在设置里用网易云 App 扫码登录。Cookie 存在 `local-music/go-music-dl/data/`。

需要 macOS 14 或更高版本（Apple 芯片），或者 macOS 15 或更高版本（Intel）。

### 能说什么

| 想做什么 | 例子 | 什么时候算 |
| --- | --- | --- |
| 点歌 | 放周杰伦的晴天、帮我播放周杰伦的晴天、来一首孤勇者、我想听陈奕迅的歌、换成林俊杰的江南、放一首叫七里香的歌 | 随时 |
| 暂停 / 继续 / 停止 | 暂停、先给我暂停、帮我把歌暂停了、继续播放、别放了、把音乐关了 | 有歌的时候 |
| 切歌 | 下一首、换首歌、跳过这首、好的下一首吧、上一首、回到上一首 | 随时 |
| 快进 / 重播 / 循环 | 快进五秒、快退十秒、往后快进一分钟、从头播放、再放一遍、单曲循环、取消循环 | 有歌的时候 |
| 问歌名 | 这是什么歌、这首歌是谁唱的呀 | 有歌的时候 |
| 音量 | 音量调到三十、音量调回三十、把电脑的声音调到百分之六十、音量最大、大声点、静音、取消静音 | 随时（"开大点""关小一点"只在有歌的时候算） |

"暂停""继续""从头开始"这些话在 Bot 任务里也常见，所以只有在放歌或暂停时才算点歌指令。另外有两条规则：
- **关键词加填充字**：句子里有控制词，去掉它以后剩下的只是"先、给我、帮我、把、这首、歌、一下、吧"这类字，才算指令。"暂停那个下载任务""把窗口关掉""跳过这一步"照旧交给 Bot。
- **识别把几句拼在一起时**（例如"周杰伦的晴天。放周杰伦的晴天。"），会拆开一句句看。

放歌期间有话没认出来、交给了 Bot，后端日志里会记一条"放歌期间未匹配，交给 Bot"，方便以后补上这种说法。

### 怎么选歌

- **说了歌手**：网易云和 QQ、酷狗、酷我、咪咕同时搜。网易云有原唱就用网易云的，没有就从其他平台挑。
- **只说歌名**：看各平台排第一的原版是谁唱的，按多数判断原唱。
- **不算原版的**：歌名里有 Live、翻唱、伴奏、remix、Demo、"……版"等字样的，专辑是演唱会、remix 合集的，都排除。冒名上传也排除，比如"周杰伦."、"HF薛之谦"；"G.E.M.邓紫棋"这类艺名照常认。
- **挑码率最高的**：同样条件的几首里挑码率最高的。比如酷我的《晴天》只有 128 kbps，咪咕有 900 多。没登录的平台拿不到播放地址时，会自动跳过。
- **歌名被识别错**（"周杰伦的请帖"）：按读音（`pypinyin`）在这位歌手的歌里找最接近的，回答"没找到请帖，给你放周杰伦的晴天"。
- **"下一首"**：找同一位歌手、还没放过的另一首原版。"上一首"回到放过的上一首。

### 回答和板子的状态

- **点歌和切歌**：板子马上说"好的""下一首"，同时开始搜，歌一放起来，屏幕上就显示"正在播放：歌手的歌名"。
- **其他指令**：用提前合成好的短句回答，说完约 0.1 秒出声；音量、快进的具体数值只显示在屏幕上。
- **回答完板子就待机**：不会把电脑放的音乐当成下一句话。要再说话，就唤醒或者按键。
- **唤醒时压低音乐**：唤醒板子时，音乐先降到 25% 的音量，说完指令或者 15 秒后恢复。
- **系统音量**：音量调的是电脑的系统音量（用 `osascript`）。

### 常见问题

| 现象 | 处理 |
| --- | --- |
| 说"放 X"后板子回答"音乐服务没能启动" | 看 `local-music/go-music-dl/service.log`；确认配置里的路径对，18080 端口没被占用 |
| 只搜到翻唱或者"没找到" | 网易云没有这首歌的版权时，会去其他平台找；常听的平台可以在 go-music-dl 里扫码登录 |
| 歌手名老是识别错 | 在配置的 `local_music.hotwords` 里加上这位歌手和歌名（会追加到语音识别的热词里），然后重启后端 |
| 说完很久才有反应 | 后端刚重启后的第一句，要等短句合成好（每句 1–3 秒），之后就快了；"这是什么歌"要现场念歌名，约 2 秒 |

## 接入小米智能音箱 Pro（可选）

给小米智能音箱 Pro（OH2P）刷 [open-xiaoai](https://github.com/idootop/open-xiaoai) 的补丁固件、装上 Client 后，音箱直接连宗主后端，就像一块没有屏幕的宗主板子：喊"宗主"，音箱回"在"，后面的话交给 Bot，回答从音箱里念出来；直接喊某个 AI 的呼名（比如 Bot 的名字）也能唤醒，并交给那个 AI。念的时候再喊"宗主"可以打断（这时不认呼名，免得音箱念到 AI 的名字时把自己叫醒）；问完新问题，它先把没念完的接着念完，再念新回答（前面带上"你刚才问……"）。小爱同学照常能用。本机点歌不接音箱：歌在电脑上放，音箱说的"暂停""放首歌"也交给 Bot。

```
音箱（补丁固件 + Client）──WebSocket 4399──▶ 宗主后端（core/gateway/xiaoai/）
```

- **音箱上**：补丁固件开 SSH、关小米自动升级、开机运行 `/data/init.sh`；open-xiaoai 的 Client 把麦克风和播放交给后端。
- **后端里**：唤醒词在后端识别（sherpa-onnx），之后和板子走同一套识别、网关、TTS。音箱按 4 个声道录音：3 个麦克风，加 1 个音箱自己放出的声音。后端只用麦克风，所以音箱说话时也能喊醒；等音箱真的放完、回声过去才开始听，不会把它自己的声音当成你的话。网关页面上显示为"小米音箱 Pro"，卡片里有型号、系统版本、启动分区、音量，可以调音量、播放 / 暂停、让它说一句话、打断小爱，也在这里改它的唤醒词。

都在网关页面上做（`http://<电脑>:8003/gateway` → 设备），后端在这台电脑上干活，不用敲命令：

1. **刷补丁固件**（只能在直接运行在 Mac 上的后端里做，Docker 里摸不到 USB）：音箱用能传数据的 Type-C 线直插电脑。在"给小米音箱刷补丁固件"里填音箱现在的系统版本（米家 App → 音箱 → 设置 → 检查更新，最好先升到最新）和要设的 root 密码，勾选知道风险，点「开始」。后端查到小米的官方包、下载、打补丁做镜像（核对只改了补丁的 8 个文件），然后提示"拔掉音箱的电源，等 3 秒再插上"：音箱一进刷机模式后端就接住，不用再点。接着把 6 个分区只读备份到电脑上（`data/xiaoai-flash/backup-*`），选边（一边的内核和系统都和官方包一样才算官方的一边，只写另一边，两边都对不上就不写；也可以自己选写 0 号还是 1 号，但另一边必须是官方的才写），写进去都读回来逐字节核对，都对了才切启动分区。刷完拔电再插。想先看看接不接得住、会写哪一边，点「只读试一次（不写）」，它做到选边就停。
2. **打开音箱接入**：在"接入小米音箱 Pro"里点「打开音箱接入」。后端生成 token，没有唤醒词模型就在后台下载（压缩包约 490 MB，只留 5 个文件，约 120 MB），下好就开 4399 端口，不用重启后端。
3. **装 Client**：填音箱 IP（路由器管理页面或米家 App 里看）和刷机时设的 root 密码，点「装到音箱上」。后端经 SSH 写入 Client、后端地址、token 和开机脚本，核对后启动；几秒后音箱"嘀"一声，连上后端。以后再点一次就是更新。

root 密码只用这一次，后端不保存；它经网关页面发给后端时没有加密，只在自己家的局域网里用。网关页面设了口令时，这些操作要先登录。

不用网页也行：[zongzhu-speaker/README.md](../zongzhu-speaker/README.md) 里有同样做法的脚本（`build_image.sh`、`backup_readonly.sh`、`flash_slot.sh`、`install_client.sh`），以及在后端配置里打开音箱接入的写法：

```yaml
gateway:
  xiaoai:
    enabled: true
    port: 4399                     # 和装 Client 时写的端口一样
    token_file: /完整路径/token.txt  # 不写就用网关页面生成的 data/xiaoai_token.txt
    # wake_words: [宗主]           # 默认"宗主"；AI 的呼名也自动算唤醒词
    # kws_threshold: 0.05          # 越低越容易唤醒
```

电脑的 IP 写进了音箱，所以要在路由器里给电脑固定一个 IP。只在 OH2P、固件 1.62.2、Apple Silicon 的 Mac 上完整做过。**刷机有变砖的风险**：网页刷机会先只读备份，只写一边、留一边官方系统当退路，但刷机工具、USB 线、断电都可能出意外。

## 手动安装（不用网页）

网页刷机和一键安装脚本做的就是下面这些事。想自己控制每一步、或者网页用不了时，照这里做。

### 1. 准备固件

两种方式任选：

- **推荐：自己编译，把后端地址编进固件**。之后配网只需要选 Wi-Fi，见第 3 步。
- **直接用发布包**：微雪 1.75C 用 `firmware/zongzhu-1.75c-2.5.2.9/`（也可从 [Releases](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest) 下载 zip），立创板用 `firmware/zongzhu-szp-2.5.2.9/`，M5Stack StopWatch 用 `firmware/zongzhu-stopwatch-2.5.2.9/`（尚未实机验证）。发布包不含你的电脑地址，配网时要手填 OTA 地址。

### 2. 后端

需要 Python 3.10、FFmpeg、Opus（`brew install python@3.10 ffmpeg opus`）。下面的命令都在仓库根目录执行：

```sh
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements-macos.txt
mkdir -p logs private/bot-replies xiaozhi-esp32-server/main/xiaozhi-server/data
chmod 700 private private/bot-replies
cp examples/backend.config.yaml xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
cp examples/grok-bot-webhook.example.json private/grok-bot-webhook.json
chmod 600 private/grok-bot-webhook.json xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
```

然后改两个配置文件：

- `private/grok-bot-webhook.json`：填 Bot Webhook 的 `url` 和 `token`；`reply_dir` 改成 `仓库绝对路径/private/bot-replies`（可以用 `echo "$PWD/private/bot-replies"` 得到）。
- `xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`：把 `192.168.1.100` 全部换成电脑的局域网 IP（macOS 上用 `ipconfig getifaddr en0` 查）。保持 `LLM: BotOnly`、`Intent: nointent`，不需要模型 API Key。

下载语音识别模型 X-ASR（约 174MB；国内下载慢可把 `https://huggingface.co` 换成 `https://hf-mirror.com`）并启动：

```sh
M=sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03
mkdir -p xiaozhi-esp32-server/main/xiaozhi-server/models/$M
for f in encoder-epoch-99-avg-1.int8.onnx decoder-epoch-99-avg-1.onnx joiner-epoch-99-avg-1.int8.onnx tokens.txt bpe.model; do
  curl -fL -o xiaozhi-esp32-server/main/xiaozhi-server/models/$M/$f https://huggingface.co/csukuangfj2/$M/resolve/main/$f
done
./start.sh
```

语音识别默认用 X-ASR，不需要 torch；热词和识别后纠错的写法见 `examples/backend.config.yaml`。想换回 FunASR（SenseVoiceSmall，约 900MB）：再装 `requirements-macos-funasr.txt`，按上游说明下载模型，把配置里的 `ASR: SherpaXASR` 改成 `ASR: FunASR`。

`start.sh` 在前台运行，关掉终端服务就停了，不要同时开多个。后端占用 8000（WebSocket）和 8003（HTTP/OTA）两个端口。

浏览器打开 `http://localhost:8003/gateway` 是网关页面，局域网里的其他设备也能打开，页面上不显示任何密钥。五页：

- **总览**：哪几块板子在线、在做什么（在听、在说、等 Bot 几秒）；各模块（点歌、Grok Bot、音箱接入、识别、合成）是否正常。
- **最近的话**：最近 30 句各走了哪一层、交给了谁、多久出声，AI 的回复也显示在下面（可以关）。只在内存里，后端重启后清空。
- **设备**：板子醒着时读到的 WiFi 和信号、IP、固件版本、内存、音量、亮度，以及板子的 MCP 工具列表；板子待机后显示上次读到的值。可以改板子音量、屏幕亮度、唤醒词（没有深浅色主题：宗主的眼睛界面固定黑底白字），重启板子，让板子进配网热点（固件有这个工具时才显示）；最上面是这台 Mac 上点歌的上一首、暂停 / 继续、下一首、停止和电脑音量。改板子的按钮只在板子醒着时能用。
- **转交任务**：最近 24 小时交给 Bot 的话：进行中、回复到了等着念、念过了、没等到回复，带问的话、回复和用时。
- **工作原理**：按现在的配置画出一句话怎么走：收音 → 识别 → 纠错和过滤 → 分派（本机技能、呼名、交给哪个 AI）→ 合成。

**更新板子固件**（"设备"里板子卡片的固件一栏）：

- **自己上传**：选编译出来的 `xiaozhi.bin`（不是合并好的整片镜像）。上传时先核对是不是 ESP32 固件、项目名、固件里有没有这块板子的型号和变体名、芯片、版本比板子新（同版本或降级要再确认），过了才存进后端的 `data/bin/`。之后点"立即更新"（板子要醒着，马上下载、重启），或者什么都不做，这个型号的板子下次开机自己更新。编只改版本号的固件：`tools/build_firmware.py ... --version 2.5.2.10`。
- **项目发布的固件**：后端启动一分钟后查一次、之后每小时查一次本项目的 GitHub Releases，只收项目主人签了名的发布（公钥写在 `core/gateway/releases.py`），只下载你这里有的板子用得上、而且比板子新的那一份，核对大小、SHA-256 和固件本身后放进 `data/bin/`，板子下次开机更新。发布的固件里内置的是占位地址，板子用自己存的后端地址（刷机网页、配网页面都会存），更新后照旧连你的后端。页面上"项目发布的固件"卡片可以关掉自动更新、点"现在查"；配置里写 `gateway.firmware_releases: false` 就完全不查。
- 固件开了回滚：新固件起不来会退回旧版。但刷错型号可能救不回来，所以别跳过上面的核对。

默认打开页面就能改。不想让局域网里的人随便改，在 `.config.yaml` 里写 `gateway.password`，页面会先要口令（见 `examples/backend.config.yaml`）。

**改唤醒词**（不用重刷固件）：最简单的是在网关页面"设备"里板子卡片的"唤醒词"填新词，点"保存并重启"（板子要醒着，先喊一声唤醒词）。也可以在仓库根目录运行 `.venv/bin/python tools/wake_word.py 你好小雨`。脚本会等你喊唤醒词叫醒板子，然后让板子重启、下载换了唤醒词的资源包（约 4–5 MB，屏幕显示进度，过程中不要断电），之后用新唤醒词。资源包要和板子的固件同一版，从 `firmware/` 里按型号和版本找（后端不在仓库里跑时，配置里写 `gateway.firmware_root` 指向仓库根目录）；只支持中文唤醒词。小米音箱的唤醒词也在网关页面上改（音箱卡片里），改完马上生效。

**呼名**：先喊"你好宗主"唤醒，再说"嗨 <Bot 的名字>，……"（"嘿"也行），后面的话直接交给这个 Bot，不经过点歌；只喊名字回一句"我在。"，什么也不提交。Bot 的名字是它在 Grok 里的名字，写在 `.config.yaml` 的 `grok_bot.bot_name`（例如 `硬件`），不写时称呼是"Grok Bot""Grok"。以后接了第二个 AI，喊谁的名字，这块板子之后就交给谁，记在 `data/agent_sessions.json`，重连、重启后照旧。称呼在网关页面"设备"的"呼名"卡片里改（可以加识别常听成的写法），改完马上生效，存在 `data/gateway_settings.json`；也可以在配置的 `gateway.call_names` 里写，页面上改过的优先。没唤醒时直接喊名字，板子听不到：板子只认它的唤醒词；小米音箱能听到，呼名也是它的唤醒词。只喊名字、回了"我在。"以后，音箱接着听你的问题。

想让后端开机自动在后台运行（进程退出会自动拉起，运行期间 Mac 不会因空闲睡眠）：

```sh
bash tools/autostart.sh enable    # 开启并马上启动；status 自检，restart 重启，disable 取消
```

仓库在"桌面""文稿""下载"里时，第一次会弹出"宗主后端"想访问文件夹的窗口，点"允许"。

**用 Docker 运行**（Windows、Linux、Mac）：后端也可以放进容器里跑（`deploy/docker/`），不用装 Python 环境；`setup` 生成配置、下载模型，配置、模型、Bot 回复都在你指定的一个文件夹里。板子、音箱、网关页面、Bot 回复都照常，本机点歌在容器里用不了。步骤见 [deploy/docker/README.md](../deploy/docker/README.md)。

### 3. 刷固件

用 USB-C 连上板子，先找串口并备份整片 Flash（出问题可以原样刷回）：

```sh
ls /dev/cu.usbmodem*
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX read-flash 0 ALL zongzhu-backup.bin
```

**方式一：编译带本机地址的固件并刷入（推荐）。** 需要 ESP-IDF 6.0.1 或更高版本：

```sh
python3 tools/build_firmware.py szp   --idf <ESP-IDF 目录> --flash /dev/cu.usbmodemXXXX --erase   # 立创板
python3 tools/build_firmware.py 1.75c --idf <ESP-IDF 目录> --flash /dev/cu.usbmodemXXXX --erase   # 微雪 1.75C
python3 tools/build_firmware.py stopwatch --idf <ESP-IDF 目录> --flash /dev/cu.usbmodemXXXX --erase   # M5Stack StopWatch（未上机）
```

固件里的 OTA 地址默认是 `http://<这台 Mac 的名字>.local:8003/xiaozhi/ota/`（名字来自 `scutil --get LocalHostName`），Mac 换了局域网 IP 也能找到。板子首次开机会把这个地址存好，配网页里能看到已经填上。编出的包在 `build-output/`，含本机名字，不会提交到仓库。

`--erase` 会清空整片 Flash（包括 Wi-Fi 设置），板子原来是别的固件时必须加，板子里手动填过 OTA 地址时也要加，否则会继续用旧地址。

**方式二：刷发布包。** 校验并写入：

```sh
cd firmware/zongzhu-1.75c-2.5.2.9   # 立创板换成 firmware/zongzhu-szp-2.5.2.9
shasum -a 256 -c SHA256SUMS
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 921600 write-flash @flash_args
```

完整分段包不写 NVS（Wi-Fi 等设置会保留），但会把 OTA 启动选择重置到分区 0。板子原来跑的是别的固件（分区表不同）时，先执行 `esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX erase-flash`。找不到串口或连接失败时，按住 BOOT 键再插 USB，进入下载模式后重试。

### 4. 配网

板子没有 Wi-Fi 设置时会自动开热点（`Xiaozhi-XXXX`）。手机连上后打开 `http://192.168.4.1`，选一个和电脑互通的 2.4GHz Wi-Fi：

- 用方式一刷的固件：**只选 Wi-Fi 并保存**，「高级选项」不用动。
- 用发布包：在「高级选项」里把 OTA 地址填成 `http://电脑局域网IP:8003/xiaozhi/ota/`。

已经配过网的板子要重新配网：开机后、连上 Wi-Fi 之前单击 BOOT（窗口只有 1–2 秒）。

### 5. 试一下

说"你好宗主"，等它回应后说"请回复三句话，介绍宗主现在的等待和朗读功能"。屏幕先显示等待秒数，Bot 写回文件后开始朗读，就说明整条链路通了。

## 常见问题

| 现象 | 先查这里 |
| --- | --- |
| 板子一直连不上服务 | 电脑和板子是否在同一网段；`.config.yaml` 和板子 OTA 地址里的 IP 是否是电脑当前的 IP；macOS 防火墙是否放行了 Python 的 8000/8003 端口 |
| 后端重启后板子一直"连接中"，要拔线重插才好 | `.config.yaml` 的 `server` 下没写 `auth_key`：后端每次启动随机换一个，板子开机时拿到的 token 就失效了。照 `examples/backend.config.yaml` 写一个固定的随机串，重启后端后再给板子上电一次，以后重启后端就不用再动板子 |
| 电脑 IP 变了 | `.config.yaml` 里的 WebSocket 地址要改。板子的 OTA 地址：用方式一（`.local` 名字）刷的不用改；手填 IP 的要在配网页改 |
| 听到"好的，正在交给 Bot"、屏幕在等待，但一直没有回复 | Bot 没把文件写到这台电脑。确认 Bot 有本机文件写入权限，写到的是 `reply_dir` 下的路径，内容里的 `request_id` 和请求里的一致 |
| 回执之后接着说"Bot 服务拒绝了请求" | Webhook 返回了 4xx，检查 `url` 和 `token` |
| 屏幕说"Bot 回传目录不可用" | `reply_dir` 不是存在且可写的绝对路径 |
| 唤醒词总是误触发或叫不醒 | 阈值在板级 `config.json` 的 `CONFIG_CUSTOM_WAKE_WORD_THRESHOLD`（当前 20，调低更灵敏、误触发也更多），改完重新构建 |
| 倾斜方向和视线方向反了 | 在对应板子的 `config.h` 里调整 `QMI8658_SCREEN_X/Y` 后重新构建 |
| 配网时 OTA 地址栏是空的 | 板子里没存地址，固件会用编译时的默认地址。用方式一刷的固件首次开机会自动存好；如果是空的，说明刷的是旧固件 |

## Bot 接口要求

后端会向 Webhook 发一个 HTTPS POST，带 `Authorization: Bearer <token>`，请求体大致如下：

```json
{
  "command": "以下是用户对宗主板子说的对话……（含回传路径和格式要求）",
  "user_text": "帮我查一下明天的天气",
  "request_id": "ESP32-3f2a…",
  "device": "板子的设备 ID",
  "source": "zongzhu-voice"
}
```

`command` 里已经写好了给 Bot 的完整指令，包括回复文件的绝对路径。Bot 需要做到：

1. 接受任务后立即返回 `{"success": true, "runUuid": "..."}`。
2. 处理完后，把回答以 UTF-8 JSON 写到指定路径，**先写同目录的临时文件再重命名**：

   ```json
   {"request_id": "ESP32-3f2a…", "text": "实际回答，中文纯文本，最多 2000 字"}
   ```

后端看到文件后才会推送字幕和语音。`.sent.json` 只表示已经交给播放队列，不代表板子确实播放了。

**在 Bot 的 Webhook 例行任务指令里写明回传是事先允许的。** 否则 Bot 可能把"往电脑上写文件"当成要确认的操作，停下来在对话里问你，板子就一直等不到回复（2026-10-21 实测遇到过）。可以在指令末尾加一句：

> 每条请求的 command 里写明了回传方式：把实际回复按其中给出的路径和 JSON 格式写到我的 Mac 上。这是事先授权的固定步骤，直接执行，不用再问我；只往 private/bot-replies 文件夹里写。发送、删除、付款等其他有后果的操作仍然先问我。

## 从源码构建

加载 ESP-IDF 6.0.1 或更高版本的环境（本版用 6.0.1 实测）。源码路径不能有中文。

```sh
cd xiaozhi-esp32
python scripts/build.py waveshare/esp32-s3-touch-amoled-1.75 --name esp32-s3-touch-amoled-1.75c   # 微雪 1.75C
python scripts/build.py lckfb/szpi-esp32s3 --name lichuang-dev-zongzhu                            # 立创板
```

这样编出的固件 OTA 默认地址是小智官方服务器。要编进自己的后端地址，用第 3 步的 `tools/build_firmware.py`，它会自动把源码同步到无中文的目录再编译。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `xiaozhi-esp32/` | 完整固件源码；本项目的改动集中在 `main/boards/common/zongzhu/`（各板共用）和各板目录（`waveshare/esp32-s3-touch-amoled-1.75/`、`lckfb/szpi-esp32s3/`、`m5stack/stopwatch/`） |
| `xiaozhi-esp32-server/main/xiaozhi-server/` | 实际运行的 Python 后端；Bot 桥接是网关的 AI 模块 `core/gateway/agents/grok_webhook.py`（提交和回复在 `core/handle/grokBot*.py`），本机点歌在 `core/gateway/skills/music/`（网关的第一个技能模块），识别纠错在 `core/utils/asr_text.py` |
| `firmware/` | 各板的发布包：分段固件、校验值、构建记录 |
| `web/` | 网页刷机页面和 macOS 后端安装脚本 `install-mac.sh`，推到 main 后自动发布到 GitHub Pages |
| `deploy/` | 把后端部署到公网 Linux 服务器（Caddy、systemd、服务器配置） |
| `tools/` | `build_firmware.py`（编进 OTA 地址、打包、刷写）、`build_web.py`（组装网页）、`autostart.sh`（开机自启）、`local_music_setup.sh`（下载点歌用的 go-music-dl 和 mpv）、`verify/`（端到端检查）、`asr-bench/`（识别对比） |
| `zongzhu-speaker/` | 小米音箱这一边：补丁、Client 源码和刷机、安装脚本，说明见它的 README；后端接音箱的代码在 `core/gateway/xiaoai/` |
| `local-music/` | `local_music_setup.sh` 下载的程序和 go-music-dl 的数据（含登录 Cookie）；只在本机，不进 Git |
| `examples/` | 不含真实凭证的配置模板 |
| `docs/` | 本文、各板说明，目录见 [docs/README.md](README.md) |
| `requirements-macos*.txt` | 后端依赖：默认（X-ASR）、可选的 FunASR、可选的 pytest、当前测试过的完整版本 |

<details>
<summary>关键文件</summary>

共用代码在 `main/boards/common/zongzhu/`：

| 文件 | 作用 |
| --- | --- |
| `eye_model.h` | 13 种表情的形状和动态（纯数学，不依赖 LVGL） |
| `eye_display.h` | 眼睛绘制、眨眼和眼神、触摸手势、字幕模式；屏幕尺寸和排版由 `EyeScreen` 传入 |
| `qmi8658_motion.h` | QMI8658 驱动，倾斜跟随和摇晃检测 |
| `ota_default.h` | 首次开机把编译时的 OTA 地址存到设置里 |

每块板自己的目录里：

| 文件 | 作用 |
| --- | --- |
| `config.h` | 引脚和 IMU 轴向映射 |
| `config.json` | 构建变体：唤醒词、1ms 系统时钟（`CONFIG_FREERTOS_HZ=1000`）等 |
| 板级 `.cc` | 屏幕排版参数、按键和工具；立创板的宗主功能由 `CONFIG_ZONGZHU_EYE_UI` 开启 |

</details>

## 测试

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m unittest tests                 # 不用另装东西；只跑一个文件：-m unittest tests.test_gateway
../../../.venv/bin/python -m pytest tests                   # 连同 pytest 写法的测试一起跑，先装 requirements-macos-test.txt
cd ../../../web && node --test test/*.test.mjs    # 网页刷机的库代码
```

`tools/verify/` 里是连真实设备链路的端到端检查（在仓库根目录运行，例如 `python tools/verify/verify_bot_reply.py`）。`verify_bot_bridge.py`、`verify_bot_reply.py`、`verify_bot_speech.py` 会真的调用你配置的 Bot（每个脚本发一条无副作用的测试任务），只在你有权限的测试环境里用，运行前先启动后端；这几个脚本和 `verify_local_music.py` 都用 macOS 合成语音模拟板子说话（共用 `sim_board.py`），需要 macOS 和 ffmpeg；`verify_bot_wait_display.py` 用本机测试文件，正常情况下不会调用 Webhook；`verify_local_music.py` 用 macOS 合成语音模拟设备说点歌指令，会在电脑上放几秒歌，不调用 Bot。

两条命令都不需要 `data/.config.yaml`，clone 下来就能跑，也不会真的发网络请求：测试只用仓库里的 `config.yaml`；没有自带模拟网络的 httpx 请求一律当作连不上（`tests/conftest.py`）。`unittest` 跑不了 pytest 写法的几个文件（`test_llm`、`test_tts` 等），会自动跳过（`tests/__init__.py`），`pytest` 两种都跑。`test_llm` 里有 3 项要真的 API Key，默认跳过；想真的请求大模型，`export RUN_LIVE_API_TESTS=1` 并在 `data/.config.yaml` 填好密钥再跑 pytest。语音识别对比用 `tools/asr-bench/`。

## 已知限制

- 说话时眼睛的起伏是按状态播放的动画，不跟音量同步。
- 动画逻辑在微雪 1.75C 上实测约 35–42 帧/秒（立创板未单独测）。显示任务优先级低于语音处理，以保证声音不卡，所以说话时偶尔会有 100ms 左右的停顿。
- 手势阈值是按测试板调的，换一种握持方式可能需要微调。
- 只能在局域网内用，电脑必须开着。
- MQTT 路径参与了编译，但没有单独做实机网络验收。
- 本机点歌：
  - go-music-dl 没有只监听本机的选项，会监听所有网卡的 18080 端口。
  - 歌放完不会自动接下一首。
  - 只说歌名、歌名又被识别错时（比如只说了"放请帖"），不会按读音纠正。
  - go-music-dl 的接口是从它的网页里看出来的，不是正式接口，升级后需要重新核对（`core/gateway/skills/music/source.py` 里有说明）。
