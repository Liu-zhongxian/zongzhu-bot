# 任务说明书：M5Stack StopWatch

创建：2026-10-22（Asia/Shanghai）。状态：**编译通过，未上机**。手上还没有这块板，下面「待实机确认」一节的内容都没验证过。

## 1. 目标

在 M5Stack StopWatch（C152）上做出和微雪 1.75C 一样的宗主，并用上 StopWatch 多出来的两个按键和震动马达。和立创板一样，作为同一份固件源码里的一个新编译选项 `m5stack-stopwatch-zongzhu`，不单独建仓库。

## 2. 板子（来自官方资料）

| 项目 | 值 |
| --- | --- |
| 型号 | M5Stack StopWatch Dev Kit（SKU C152），[官方文档](https://docs.m5stack.com/en/core/StopWatch) |
| 主控 | ESP32-S3R8，16MB Flash，8MB PSRAM（Octal） |
| 屏幕 | 1.75 寸圆形 AMOLED，466×466，CO5300，QSPI；复位和供电走 M5IOE1 |
| 触摸 | CST820B @0x15，INT G13，复位 M5IOE1 P4 |
| 姿态传感器 | BMI270 @0x68，系统 I2C（SDA G47，SCL G48） |
| 音频 | ES8311 + 单 MEMS 麦克风，AW8737A 功放（M5IOE1 P10） |
| 按键 | A（黄）G2，B（蓝）G1，另有电源键 |
| 震动 | 马达在 M5IOE1 IO9（PWM 通道 1） |
| 电源 | M5PM1，450mAh 电池 |

## 3. 和微雪 1.75C 的差异

| 项目 | 微雪 1.75C | StopWatch | 处理 |
| --- | --- | --- | --- |
| 屏幕 | CO5300 466×466 | 同一颗 | 眼睛和字幕布局不改 |
| 触摸 | CST9217 | CST820B | 用 CST816S 驱动（协议兼容）；上游 M5 板型本来没接触摸 |
| 姿态传感器 | QMI8658 | BMI270 | 新增 `bmi270_motion.h`；倾斜 / 摇晃判定抽到 `motion_gesture.h` 两边共用 |
| 音频 | ES8311 + ES7210，有回采 | 只有 ES8311 | 不开设备端回声消除，说话时插话效果会差一些 |
| 按键 | BOOT 一个 | A / B 两个 | 见第 4 节 |
| 震动 | 无 | 有 | 按键、触摸反应、摇晕时短震 |
| 电源 | AXP2101 | M5PM1 + M5IOE1 | 沿用上游 M5 板型代码 |

## 4. 按键

| 操作 | 作用 |
| --- | --- |
| A 单击 | 开始 / 结束对话（开机未联网时进入配网） |
| A 长按 | 切换字幕模式（完整 → 简洁 → 关闭） |
| B 单击 | 音量 +10%，到 100% 后回到 0（上游 M5 板型原有） |
| B 长按 | 震动开 / 关，保存在 NVS |

触摸和摇晃手势和 1.75C 相同。

## 5. 构建

```sh
python3 tools/build_firmware.py stopwatch --idf <ESP-IDF 目录>
```

2026-10-22 用 ESP-IDF 6.0.1 编译通过。同一天重新编译了 1.75C 和立创板，确认共用代码的改动没有影响它们。

发布包在 `firmware/zongzhu-stopwatch-2.5.2.9/`，网页刷机也已列出这块板。发布包和其他板一样只带上游默认 OTA 地址，刷机时要填自己的后端地址。网页刷机过程中用到的资源分区唤醒词读写，已用这个包在本机测过。

## 6. 待实机确认

1. 启动日志有 `BMI270 at 0x68 ready`、`Touch panel initialized`，没有 `Vibration motor PWM not available`。
2. 触摸方向：按住屏幕左边拖动，眼睛往左看。反了就改 `m5stack_stopwatch.cc` 里触摸配置的 `mirror_x` / `mirror_y`。
3. 倾斜方向：往右倾，眼睛往右看。反了就改 `config.h` 里的 `BMI270_SCREEN_X/Y`（现在照社区 KK 固件写的是 X = a[1]，Y = a[0]）。
4. 左右用力摇 4 下出现螺旋眼，放稳后恢复。
5. 震动强度、喇叭音量、真实麦克风唤醒和整条 Bot 对话。

第一次刷之前，先用 `esptool read-flash 0 ALL` 把原厂固件备份下来，再带 `--erase` 刷入。StopWatch 没有 BOOT 键，连不上时长按复位键约 2 秒，绿灯亮后松开，进入下载模式。
