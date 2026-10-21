# 任务说明书：网页刷机

创建：2026-10-20（Asia/Shanghai）。状态：**第一版已写好，待实机验收**（2026-10-20）。页面在 `web/`，库代码测试通过，本机浏览器能正常加载；还没有用真板子在网页上完整刷过一次。

## 1. 目标

公开给别人用：用户用 USB 把板子接到电脑，打开一个网页，按步骤点完就装好宗主固件，不用装 ESP-IDF、esptool 或任何软件。

网页流程：

1. 识别板子型号，判断是否支持
2. 选择唤醒词
3. 选择 UI 样式（第一版只有眼睛；IKUN 显示"即将推出"）
4. 后端在哪里运行：自己的电脑（默认），或自己的服务器
5. 联网：现在填 Wi-Fi（默认），或跳过、刷完用手机配网
6. 刷入固件，读开机日志，告诉用户有没有联网、连上后端

## 2. 已定的方案（2026-10-20 用户确认）

| 问题 | 决定 |
| --- | --- |
| 页面放哪里 | 当前仓库 `web/`，GitHub Actions 发布到 GitHub Pages。以后可能迁到 `52drunk.com` 上的自建网站，页面是纯静态文件，直接搬过去即可 |
| 谁来用 | 公开给别人 |
| 后端 | 默认装在用户自己的电脑上（按 README「后端」一节）；有服务器的用户自己按 `deploy/README.md` 部署。**页面不提供、也不默认填写我们的服务器**，用户的板子不会连到我们这里 |
| 联网 | 两种都保留，默认现在填 Wi-Fi |
| UI | 第一版只做眼睛样式；IKUN 等素材授权确认后再做 |

## 3. 已核实的技术事实（2026-10-20）

| 项目 | 事实 | 处理 |
| --- | --- | --- |
| 浏览器 | 网页串口（Web Serial）只有桌面版 Chrome / Edge 支持 | 不支持时页面顶部提示换浏览器 |
| 刷写库 | 乐鑫 `esptool-js` 0.6.1（Apache-2.0），放在 `web/vendor/`，npm 包完整性哈希已与官方记录核对 | 不依赖 CDN 刷机 |
| 唤醒词 | 固件优先读资源分区 `index.json` 的 `multinet_model`（`custom_wake_word.cc`） | **浏览器里直接改资源分区，不用为每个唤醒词单独构建**。打包格式与 `build_default_assets.py` 一致，测试证明重新打包和原文件逐字节相同 |
| 后端与唤醒词 | 原来后端只认配置里 `wakeup_words` 列出的词；不在列表里的唤醒词会被当成用户说的话**提交给 Bot** | 已改：Bot 模式下记住板子报上来的唤醒词（见第 5 节） |
| 固件里写死的唤醒词 | 只有等待界面的一句提示"说'你好宗主'或按键可追加指令" | 源码已改为"唤醒或按键可追加指令"，**下次编译固件才生效**；当前 2.5.2.9 发布包仍显示原句 |
| 首次安装 | 原固件分区布局可能不同 | 页面固定整片擦除，要求用户勾选确认 |
| 两块板分区 | 都是 nvs `0x9000`（16K）、程序 `0x20000`、资源 `0x800000`（8M） | 共用一套写入逻辑 |
| Wi-Fi 存储 | `wifi` 命名空间 `ssid`、`password`（`channel` 可选）；OTA 地址 `wifi:ota_url`；client-id `board:uuid` | 浏览器生成 NVS，用 ESP-IDF `nvs_tool.py` 校验通过 |

## 4. 页面实现

| 文件 | 作用 |
| --- | --- |
| `web/index.html`、`style.css`、`app.js` | 页面和流程：顶部步骤条，一次只显示一步，填好当前步才能点"下一步"，已完成的步骤可以点回去改 |
| `web/install-mac.sh` | macOS 后端一键安装脚本，和页面放在一起发布，第 4 步给出复制命令和下载链接 |
| `web/boards.json` | 支持的板子：芯片、Flash 大小、外观说明、对应的 `firmware/` 发布包 |
| `web/wakewords.json` | 预设唤醒词（目前只有实测过的"你好宗主"） |
| `web/lib/nvs.js` | 生成 NVS 分区（client-id、OTA 地址、可选 Wi-Fi） |
| `web/lib/assets.js` | 读写资源分区，替换唤醒词并重算校验和 |
| `web/lib/md5.js`、`appdesc.js` | 写入校验用的 MD5；读取板上现有程序的版本 |
| `web/test/lib.test.mjs` | 11 项测试，`cd web && npm test` |
| `tools/build_web.py` | 把 `web/` 和固件发布包组装成站点 `_site/`，校验 SHA256SUMS，生成每块板的 `manifest.json` |
| `.github/workflows/pages.yml` | 推送到 main 后测试、组装、发布到 Pages |

各步要点：

1. **识别**：读芯片、Flash 大小、MAC 和板上现有程序版本。按芯片 + Flash 大小列出候选；只有一个候选时自动选中。16MB 时提示"不带 C 的微雪 1.75 也是 16MB，本页不支持"，让用户对照屏幕形状确认。
2. **唤醒词**：预设或自定义。自定义时填汉字，拼音自动填写（从 jsDelivr 加载 `pinyin-pro` 3.27.0，加载失败就手填），校验字数和拼音个数一致。阈值沿用固件的 0.2。
3. **后端**：选"我自己的电脑"时，macOS 显示一键安装命令 `/bin/bash -c "$(curl -fsSL 页面地址/install-mac.sh)"`（地址按页面所在域名自动生成，迁站不用改）和下载链接；其他系统提示按 README 手动安装。网页本身不能在电脑上运行程序，只能让用户复制到终端运行。本机填电脑名（`xxx.local`）或局域网 IP，页面拼成 `http://地址:8003/xiaozhi/ota/`；服务器填完整 OTA 地址，格式规则和 `tools/build_firmware.py` 一致，非 https 给出提醒。
4. **联网**：Wi-Fi 名称最多 32 字节，密码留空或 8–63 字节，提示只支持 2.4GHz。
5. **刷入**：下载并校验每段 SHA-256 → 按唤醒词改资源分区 → 生成 NVS（新的随机 client-id）→ 整片擦除 → 写入并 MD5 校验 → 复位 → 读 45 秒开机日志。根据日志显示：已连上后端 / 开了配网热点（Wi-Fi 填错或选择了跳过）/ 连上 Wi-Fi 但连不上后端。最后显示 MAC、client-id、后端地址，选了服务器时提醒加入白名单。

## 5. 后端改动（唤醒词）

- `core/handle/textHandler/listenMessageHandler.py`：Bot 模式下，板子发来的 `listen/detect` 文本记为这块板子的唤醒词，按唤醒处理（播放问候），不提交给 Bot。
- `core/handle/grokBotHandle.py`：`strip_wake_phrase` 增加按板子唤醒词精确去除（忽略中间标点）；"你好宗主"的模糊规则保留。
- 新增 3 项测试，本项目后端测试 46 项通过。
- 已知边界：在 Bot 模式下，任何 `detect` 文本都会被当作唤醒词。正常固件只在唤醒时发送 `detect`，所以没有影响；如果有客户端用 `detect` 发文字聊天，会被当成唤醒。

## 6. 后端安装脚本（`web/install-mac.sh`）

1. 检查 Python 3.10、FFmpeg、Opus，已有能用的就跳过，只用 Homebrew 装缺的；装的时候关掉 Homebrew 自动更新，不升级已装的软件（没有 Homebrew 就提示去 brew.sh 安装后重跑）。已装 `ffmpeg-full` 也算有（它是 keg-only，`start.sh` 会把它加进 PATH）；`ffmpeg-full` 装了但运行不了时，提示先 `brew upgrade ffmpeg-full`，不在旁边另装 `ffmpeg`。原因：2026-10-21 实测，脚本在已有 `ffmpeg-full` 的电脑上照装 `ffmpeg`，顺带把 `x265` 升到 4.3，原来的 `ffmpeg-full` 8.1.1 找不到 `libx265.216.dylib`，后端启动失败
2. 从 GitHub 下载 `main` 分支代码包，只取后端需要的部分放到 `~/zongzhu`（`ZONGZHU_DIR`、`ZONGZHU_REF` 可改）。**所以后端改动要先推到 main，用户装到的才是新版**
3. 建 `.venv` 并安装 `requirements-macos.txt`
4. 在终端询问 Bot Webhook 地址和 token（token 输入不显示），写入 `private/grok-bot-webhook.json`（权限 600）；直接回车就保留模板，以后再改
5. 按默认网卡的局域网 IP 生成 `.config.yaml`
6. 下载 SenseVoiceSmall 模型
7. 显示 `电脑名.local` 和 IP 让用户填回网页，再让用户选择启动方式：开机自启（`tools/autostart.sh enable`）或手动启动（询问是否立即前台运行 `start.sh`）。两者没有默认项；已开着自启时更新后直接重启

重复运行即更新：代码覆盖，已有的 Webhook 设置、后端配置、模型和 `.venv` 保留。

已测（2026-10-20，沙箱目录，Homebrew、pip、模型下载用替身）：不填 Bot 地址、填 Bot 地址、重复运行保留配置三条路径都正确，生成的两个配置文件权限都是 600。**还没在一台全新的 Mac 上完整跑过。**

已知限制：Python 3.10 在 Homebrew 已标记弃用，2027-10-01 停用，之前需要升级后端的 Python 版本；`start.sh` 写死了 `/opt/homebrew`，Intel Mac 未测试。

## 7. 本机试用

```sh
python3 tools/build_web.py
python3 -m http.server -d _site 8000
```

用 Chrome 打开 `http://localhost:8000`（localhost 也允许网页串口）。

## 8. 待办

### 已完成

- [x] 页面、库代码、11 项测试（含 ESP-IDF `nvs_tool.py` 校验）
- [x] 站点组装脚本、Pages 发布流程
- [x] 后端支持板子自选的唤醒词，46 项测试通过
- [x] 等待界面提示去掉写死的唤醒词（源码）
- [x] 无界面 Chrome 加载检查：脚本无报错，桌面和 390px 手机宽度排版正常

### 阶段 4：验收（需要实物）

- [x] 立创板：网页完整刷一次（填 Wi-Fi），开机日志显示连上后端（2026-10-21，用户实测：`.local` 地址解析成功，`Activation done`）
- [x] 立创板：说唤醒词完成一轮 Bot 对话（2026-10-21 18:23）。第一次没回复：新建的"演示" Bot 指令里没写"回传是事先允许的步骤"，Bot 停下来问用户。在指令里加上"回传直接执行，只写 `private/bot-replies/`；发送、删除、付款仍先问"后重测：识别后同一秒播回执，约 19 秒收到回传并逐句朗读。**用户自己新建 Bot 时也要加这一句**，README 的 Bot 接口要求一节应写明
- [x] 修复第 6 步刷完后的显示：以前刷好后仍显示"正在看它能不能联网…"和转动的进度条，还有红字"板子没有连接"（刷完网页会主动断开串口）。现在出结果时收起进度条，提示改为"已经刷好。要再刷一次，请回到第 1 步重新连接板子"（灰色）；重新连接后恢复原提示
- [ ] 跳过 Wi-Fi 路径：刷完出现热点，手机配网成功
- [ ] 自定义唤醒词实测一个（例如"你好小雨"），确认能唤醒、后端不把唤醒词提交给 Bot
- [ ] 微雪 1.75C 刷一次
- [ ] Windows 的 Chrome 测一次
- [ ] 安装脚本在一台没装过后端的 Mac 上完整跑一次（含 Homebrew 安装、依赖、模型下载、启动后板子能连上）

### 发布前

- [ ] 把本次后端改动（唤醒词）推到 main，安装脚本才会装到新版
- [ ] 仓库 Settings → Pages → Source 选 GitHub Actions（一次性）
- [ ] README 首页加网页刷机入口
- [ ] 按新源码重新编译两块板的固件（带新的等待提示），更新 `firmware/` 发布包
- [ ] 预设唤醒词：再实测 2–3 个加入 `wakewords.json`

### 以后

- [ ] IKUN 样式：素材授权确认 → Kconfig 选项 → 接入现有等待、回复逻辑 → 立创重新排版
- [ ] 迁到 `52drunk.com` 自建网站
- [ ] Windows / Linux 的后端安装脚本
- [ ] 回复到达后自动接收（见 `REMOTE-PLAN.md`「待做」）

## 9. 风险与注意

| 项目 | 说明 |
| --- | --- |
| 公开仓库里的 IKUN 素材 | `xiaozhi-esp32/main/boards/waveshare/esp32-s3-touch-amoled-1.75/ikun/` 的 GIF 已在公开仓库，需确认授权 |
| 自定义唤醒词效果 | MultiNet 对不同词的效果差别大，页面标"效果因词而异"，预设只放实测过的 |
| 重刷会换 client-id | 每次网页刷机都生成新的 client-id；开了白名单的服务器要更新登记 |
| Wi-Fi 密码 | 只在浏览器内存里，写进板子 NVS，页面是静态文件，没有任何上传。日志里不显示密码 |
