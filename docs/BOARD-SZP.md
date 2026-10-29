# 任务说明书：立创·实战派 ESP32-S3 板

创建：2026-10-19（Asia/Shanghai）。状态：**已上机，待实机验收**（2026-10-19）。固件运行正常，用户反馈没有问题；OTA 地址已改为编译时写入，配网只需 Wi-Fi；README 已更新。剩余事项见第 8 节。

## 1. 目标

在立创·实战派 ESP32-S3 上做出和微雪 1.75C 一样的宗主：语音交给 Grok Bot、等待和朗读、眼睛表情、触摸手势、倾斜跟随和摇晕、字幕模式。

本轮约束（用户要求）：

- 不单独建仓库或文件夹，作为同一份固件源码里的一个新板型变体。
- 先连 **Mac 本机后端**，不测试服务器。

## 2. 板子（2026-10-19 从实物读取）

| 项目 | 值 |
| --- | --- |
| 型号 | 立创·实战派 ESP32-S3（LCKFB SZPI），模组 ESP32-S3-WROOM-1-N16R8 |
| Flash / PSRAM | 16MB / 8MB（Octal，AP 3V） |
| 屏幕 | 2.0 寸 IPS，320×240，ST7789，SPI，背光 GPIO42 低电平有效 |
| 触摸 | FT6336（FT5x06 驱动） |
| 姿态传感器 | QMI8658，与音频共用 I2C（SDA GPIO1，SCL GPIO2） |
| 音频 | ES8311 + ES7210，NS4150B 功放（经 PCA9557 扩展 IO 控制），双麦克风 |
| 按键 | 复位键 + 用户键（BOOT，GPIO0） |
| MAC | `94:a9:90:2d:a3:70` |
| 原有固件 | muse-gadget（ESP-IDF 6.0.1，2026-10-12 本机编译），用户同意直接覆盖 |

来源：`esptool chip-id`、板上分区表与应用描述、`muse/开发板参数.png`、`muse/firmware/lichuang-szp/README.txt`。

## 3. 和微雪 1.75C 的差异

| 项目 | 微雪 1.75C | 立创实战派 | 处理 |
| --- | --- | --- | --- |
| 屏幕 | 466×466 圆形 AMOLED | 320×240 矩形 IPS | 眼睛和字幕重新排版；圆屏避让角落的处理不用 |
| 触摸芯片 | CST9217 | FT6336 | 用上游实战派板的驱动 |
| 电源 | AXP2101，有电池 | 无电池管理 | 不做省电关机 |
| 姿态传感器 | QMI8658 | QMI8658 | 共用驱动；I2C 地址自动探测，轴向需实测 |
| 摄像头 | 无 | 有接口 | 保留上游初始化，不在本轮功能里使用 |

## 4. 方案

- **板型**：在上游 `main/boards/lckfb/szpi-esp32s3` 下新增变体 `lichuang-dev-zongzhu`。上游原变体 `lichuang-dev` 不改。变体名就是板子上报给 OTA 的板型标识，和普通实战派固件区分开。
- **共用代码**：眼睛模型、眼睛界面、IMU 驱动移到 `main/boards/common/zongzhu/`，两块板共用。屏幕尺寸和排版做成参数，微雪沿用原来的数值，行为不变。
- **新开关**：Kconfig `CONFIG_ZONGZHU_EYE_UI`，只在宗主变体里打开。
- **唤醒词和系统设置**：和 1.75C 一样（「你好宗主」、MultiNet7、阈值 20、1ms 系统时钟）。
- **后端**：不用改。Mac 本机后端没开设备白名单，新板可以直接连。

## 5. 待办

### 阶段 1：准备

- [x] 读取板子型号和现有固件
- [x] 整片备份 16MB Flash：`backups/szp-94a9902da370-muse-before-zongzhu-20261019.bin`，SHA-256 已校验（本机，不进仓库）

### 阶段 2：代码

- [x] 共用代码移到 `boards/common/zongzhu/`，屏幕参数化（`EyeScreen`，默认值即 1.75C 原数值）
- [x] 微雪 1.75C 重新编译通过（应用 2,869,520 字节，比 2.5.2.9 发布包多 128 字节，来自排版参数改为运行时读取）；排版参数默认值即原数值，未刷机实测
- [x] 新增 `lichuang-dev-zongzhu` 变体：眼睛界面、触摸手势、IMU、宗主工具（长按 BOOT 切字幕，所以不提供上游的「按住说话」）
- [x] 编译通过：应用 2,842,416 字节（4MB 分区内），资源 4,166,180 字节；配置项全部生效；板型标识 `lichuang-dev-zongzhu`

### 阶段 3：刷机与配网

- [x] 擦除整片 Flash 后写入，五个分段哈希校验通过；固件包 `firmware/zongzhu-szp-2.5.2.9/`
- [x] 板子自动进入配网模式。第一次手动填了 OTA 地址；之后改为编译时写入（见第 7 节），重新擦除刷机后**只配 Wi-Fi** 即连上 Mac

首次启动（串口）：眼睛界面就绪；QMI8658 在 0x6A；ES8311/ES7210 正常；摄像头识别为 GC0308；无 Wi-Fi 设置，自动进入配网模式，热点 `Xiaozhi-A371`。

### 阶段 4：实机验收

- [ ] 屏幕方向、眼睛排版、字幕三种模式
- [ ] 触摸：单击、双击、长按、拖动、滑动
- [ ] 倾斜方向正确（必要时调整轴向映射）、摇晕
- [x] 「你好宗主」唤醒 → Bot 提交 → 等待 → 朗读（2026-10-20 经测试服务器，用户确认板子收到）
- [ ] 帧率和内存（串口统计）

### 阶段 5：收尾

- [x] 固件包放到 `firmware/zongzhu-szp-2.5.2.9/`（发布包，OTA 默认为小智官方地址，不含本机名字）
- [x] README（中英文）增加立创板说明、`tools/build_firmware.py` 用法、只配 Wi-Fi 的流程（提交 `040aa5c`）
- [ ] 本文件更新为完成状态

## 6. 回退

整片备份可以原样写回，恢复 muse-gadget：

```sh
esptool --chip esp32s3 --port <串口> write-flash 0 backups/szp-94a9902da370-muse-before-zongzhu-20261019.bin
```

更早的出厂备份：`muse/backups/original-94a9902da370-20261007.bin`。

## 7. OTA 地址编译时写入（2026-10-19）

用户要求：配网时只连 Wi-Fi，OTA 地址不用手填。

- 新工具 `tools/build_firmware.py`：生成临时板级配置（只在构建目录，不进仓库），追加 `CONFIG_OTA_URL`，编译后检查 sdkconfig 确实带上该地址才打包。
- 默认地址用 Mac 的 Bonjour 名字：`http://<LocalHostName>.local:8003/xiaozhi/ota/`。固件已开启 `CONFIG_LWIP_DNS_SUPPORT_MDNS_QUERIES`，可解析 `.local`；Mac 换 IP 不影响。
- 换服务器：`--ota-url https://zongzhu.52drunk.com/xiaozhi/ota/`。
- 输出到 `build-output/`（已忽略），因为包里带有本机名字。仓库里的 `firmware/zongzhu-szp-2.5.2.9/` 是不带本机地址的发布包。
- 板子上保存过的 OTA 地址优先于编译时默认值；已手动填过地址的板子需要擦除或在配网页改回。

第一次实测（**未达到目标**）：配网页的 OTA 栏只显示板子里已保存的地址，新擦除的板子这一栏是空的，看起来必须填写，用户又手动填了 `http://192.168.124.158:8003/...`。读 NVS 确认保存的是手填的 IP，不是编译进去的地址。之前据串口「连上 Mac」判断为成功，是误判。

修正：新增 `boards/common/zongzhu/ota_default.h`，两块宗主板首次开机时，若 NVS 里没有 `ota_url`，就把编译进去的 `CONFIG_OTA_URL` 存进去；已保存的地址不覆盖。这样配网页的 OTA 栏打开时已经填好。

第二次实测（通过）：擦除后刷入，首次开机 NVS 即为 `http://DrunkdeMacBook-Pro.local:8003/xiaozhi/ota/`；用户只选 Wi-Fi，未保存高级选项；串口显示 `Established new connection to DrunkdeMacBook-Pro.local:8003`，OTA 检查通过，进入待机。

仍是固定 IP 的地方：Mac 后端下发给板子的 WebSocket 地址（`ws://192.168.124.158:8000/...`）。改成 `.local` 会同时影响两块板子，待用户确认。

## 8. 当前状态与待确认（2026-10-19）

| 项目 | 状态 |
| --- | --- |
| 立创板 | 2026-10-20 起 NVS 里的 OTA 地址改为测试服务器（固件未重刷）；此前经 `.local` 连 Mac 后端 |
| 微雪 1.75C | 仍是旧固件，OTA 地址是配网时手填的 IP；共用代码重构后只编译验证，**未重刷** |
| Mac 后端 WebSocket 地址 | 仍是 `ws://192.168.124.158:8000/xiaozhi/v1/`（固定 IP）。可改为 `ws://<Mac名>.local:8000/xiaozhi/v1/`，会同时影响两块板，**待用户确认** |
| 服务器方案 | 2026-10-20 立创板已切到 `zongzhu.52drunk.com`，完整对话实机通过，见 `REMOTE-PLAN.md` 第 8 节 |

待办：

- [ ] 用户确认后，后端 WebSocket 改 `.local` 并重启，用立创板验证
- [ ] 阶段 4 实机验收（倾斜轴向 `QMI8658_SCREEN_X/Y` 是推测值，需实测；帧率未测）
- [ ] 可选：微雪 1.75C 用 `tools/build_firmware.py 1.75c --erase` 重刷，同样改为只配 Wi-Fi
