# open-xiaoai Client（Rust）

音箱上跑的程序：把麦克风音频和小爱的事件（识别结果、播放状态）转给电脑上的 bridge，并执行 bridge 发来的指令（播放音频、运行脚本）。

- 源码来自 [coderzc/open-xiaoai](https://github.com/coderzc/open-xiaoai) 提交 `14e1034ba75698be7d3f331b9822b7043deaf032` 的 `packages/client-rust/`，代码没有改动。这个 fork 比 [idootop/open-xiaoai](https://github.com/idootop/open-xiaoai) 原版多一处：连接时带环境变量 `OPEN_XIAOAI_TOKEN`（`Authorization: Bearer`），bridge 靠它认人。
- 只放了编译需要的 `Cargo.toml`、`Cargo.lock`、`src/`。原项目的安装脚本（`boot.sh` 会从 gitee 下载 Client）没有放进来；安装用 [`../install_client.sh`](../install_client.sh)，开机脚本用 [`../init.sh`](../init.sh)。
- 许可证：MIT，见 [`../../LICENSE.open-xiaoai`](../../LICENSE.open-xiaoai)。

编译：`bash ../build_client.sh`（目标 `armv7-unknown-linux-gnueabihf.2.25`）。在 Mac 上编出来的 SHA-256 是 `ec2a78a80d3ea71b8df584526a332b1872fc65aecd15f89aaee7b96ccb7101bd`。
