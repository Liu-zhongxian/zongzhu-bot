"""音箱的设备信息（G19d 第 1 步）：网关设备页上显示型号、序列号、系统版本、启动分区、音量。

经 Client 的 run_shell 在音箱上跑一段固定的只读命令（不接收页面传来的命令）。这些命令是
2026-11-02 在音箱上查出来的（debug.inspect）：micocfg_model、micocfg_sn、micocfg_mac 打印型号、
序列号、MAC；/usr/share/mico/version 里有系统版本（ROM）、渠道、硬件平台；fw_env -g boot_part 是
当前从哪个分区启动（刷了补丁的是 boot0，官方系统留在 boot1）；mediaplayer 的 player_get_play_status
给音量（0–100）和播放状态。
"""
import json
import time

INFO_SCRIPT = "; ".join([
    'echo "model=$(micocfg_model 2>/dev/null)"',
    'echo "sn=$(micocfg_sn 2>/dev/null)"',
    'echo "mac=$(micocfg_mac 2>/dev/null)"',
    'echo "boot=$(fw_env -g boot_part 2>/dev/null)"',
    # "\toption ROM '1.62.2'" -> "rom=1.62.2"
    "awk -F\"'\" '/option (ROM|CHANNEL|HARDWARE) /{split($1, a, \" \"); print tolower(a[2]) \"=\" $2}' "
    "/usr/share/mico/version 2>/dev/null",
    "echo \"play=$(ubus call mediaplayer player_get_play_status 2>/dev/null | tr -d '\\n')\"",
])
# mediaplayer 的 status：0 没在放，1 在放，2 暂停（mphelper mute_stat 也是这么分的）
PLAY_STATES = {0: "idle", 1: "playing", 2: "paused"}


def parse(stdout):
    """INFO_SCRIPT 的输出 -> {model, sn, mac, boot, rom, channel, hardware, volume, play}，读不到的不放"""
    info = {}
    for line in (stdout or "").splitlines():
        key, _, value = line.partition("=")
        value = value.strip()
        if not value:
            continue
        if key == "play":
            try:
                play = json.loads(json.loads(value).get("info") or "{}")
            except (ValueError, AttributeError):
                continue
            if isinstance(play.get("volume"), int):
                info["volume"] = play["volume"]
            if play.get("status") in PLAY_STATES:
                info["play"] = PLAY_STATES[play["status"]]
        elif key in ("model", "sn", "mac", "boot", "rom", "channel", "hardware"):
            info[key] = value
    return info


async def read(link):
    """在音箱上读一次；返回 parse 的结果加 read_at（time.time()）"""
    result = await link.call("run_shell", INFO_SCRIPT, timeout=10) or {}
    info = parse(result.get("stdout", ""))
    info["read_at"] = time.time()
    return info
