# 文档目录

[返回首页](../README.md)

## 使用

| 文档 | 内容 |
| --- | --- |
| [GUIDE.md](GUIDE.md)（[English](GUIDE.en.md)） | 完整说明：功能细节、手动安装、刷机、配网、常见问题、Bot 接口、从源码构建、仓库结构、测试、已知限制 |
| [BOARD-SZP.md](BOARD-SZP.md) | 立创·实战派 ESP32-S3 的移植和实测 |
| [BOARD-STOPWATCH.md](BOARD-STOPWATCH.md) | M5Stack StopWatch：编译通过，还没上过实机 |
| [../deploy/README.md](../deploy/README.md) | 把后端部署到公网服务器，电脑可以关机 |

## 开发记录（`records/`）

按时间留下的方案、过程和验收证据，写的是当时的状态，不一定是现在的用法。用法以 [GUIDE.md](GUIDE.md) 为准。

| 文档 | 内容 |
| --- | --- |
| [records/VALIDATION.md](records/VALIDATION.md) | 各版本的测试范围、实测结果和限制 |
| [records/TASK-RECORD.md](records/TASK-RECORD.md) | 从接入 Grok Bot 到 2.5.2.x 的实施过程（脱敏） |
| [records/REFERENCE-TASKS.md](records/REFERENCE-TASKS.md) | 参考四个仓库的改进：即时回执、开机自启、X-ASR 识别与对比数据 |
| [records/WEB-FLASH.md](records/WEB-FLASH.md) | 网页刷机和一键安装脚本的设计与测试 |
| [records/REMOTE-PLAN.md](records/REMOTE-PLAN.md) | 脱离电脑和局域网（服务器部署）的计划与进度 |

2026-10-22 整理：开发记录移到 `docs/records/`，根目录的 `verify_bot_*.py` 移到 `tools/verify/`。旧记录里提到的原路径没有改。
