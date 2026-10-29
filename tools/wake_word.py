"""G8b：改板子的唤醒词，板子重启、下载资源包后生效，不用重刷固件。

    .venv/bin/python tools/wake_word.py 你好小雨
    .venv/bin/python tools/wake_word.py 你好小雨 --pinyin "ni hao xiao yu" --device a3:70

在运行后端的这台电脑上跑。步骤：
  1. 从 firmware/ 里找和板子同型号、同版本的资源包（资源包里还有字库和表情，必须同一版）；
  2. 板子待机时连接是断的，脚本会等你喊唤醒词把它叫醒；
  3. 后端换掉资源包里的唤醒词，把下载地址发给板子，再让板子重启；
  4. 板子开机下载约 4–5 MB（屏幕显示进度），之后用新唤醒词。下载过程中不要断电。
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "xiaozhi-esp32-server/main/xiaozhi-server"))
from core.gateway.wake_assets import check_wake_word, pinyin_command, read_assets, wake_word_of  # noqa: E402

# 板子上报的型号（OTA 的 board.type）里带的字 → web/boards.json 的 id
BOARD_IDS = (("lichuang", "szp"), ("amoled-1.75", "1.75c"), ("stopwatch", "stopwatch"))


def package_assets(board):
    """firmware/ 里和这块板子同型号、同版本的资源包；找不到时说明原因。"""
    board_id = next((i for key, i in BOARD_IDS if key in board["type"]), None)
    if board_id is None:
        return None, f"不认识的板子型号 {board['type'] or '（未知）'}，请用 --assets 指定资源包"
    entry = next(b for b in json.loads((ROOT / "web/boards.json").read_text()) if b["id"] == board_id)
    if not entry["package"].endswith("-" + board["version"]):
        return None, (f"板子上是 {board['version'] or '未知版本'}，firmware/ 里是 {entry['package']}：资源包必须和固件同一版，"
                      "请先刷同一版固件，或用 --assets 指定对应版本的资源包")
    return ROOT / "firmware" / entry["package"] / entry["assets"], None


def wait_for_board(client, device, timeout):
    """等板子连上（待机时连接是断的）；返回网关页面上的这块板子。"""
    deadline = time.monotonic() + timeout
    asked = False
    while time.monotonic() < deadline:
        boards = client.get("/gateway/api/status").json()["boards"]
        if device:
            boards = [b for b in boards if b["id"].lower() == device.lower()[-5:]]
        online = [b for b in boards if b["online"]]
        if len(online) == 1:
            return online[0]
        if len(online) > 1:
            sys.exit("有好几块板子连着，请用 --device 指定（网关页面上的编号，如 a3:70）")
        if not boards:
            sys.exit(f"网关页面上没有板子 {device}" if device else "网关页面上还没有板子")
        if not asked:
            print("板子待机中，连接是断的：现在对它喊唤醒词，把它叫醒……")
            asked = True
        time.sleep(0.5)
    sys.exit("等了一会儿板子还没连上，请重新运行")


def main():
    parser = argparse.ArgumentParser(description="改板子的唤醒词（重启板子后生效）")
    parser.add_argument("text", help="新唤醒词，中文，如 你好小雨")
    parser.add_argument("--pinyin", help="拼音，不带声调，ü 写成 v；不填时自动生成")
    parser.add_argument("--device", help="板子编号（网关页面上的，如 a3:70）；只连着一块板子时可以不填")
    parser.add_argument("--assets", type=Path, help="用这个资源包，而不是 firmware/ 里和板子同版本的")
    parser.add_argument("--server", default="http://127.0.0.1:8003", help="后端地址（要在本机）")
    parser.add_argument("--no-reboot", action="store_true", help="只把地址发给板子，你自己重启")
    parser.add_argument("--yes", action="store_true", help="不再确认")
    parser.add_argument("--wait", type=float, default=60, help="等板子连上的秒数")
    args = parser.parse_args()

    command = args.pinyin.strip().lower() if args.pinyin else pinyin_command(args.text)
    reason = check_wake_word(args.text, command)
    if reason:
        sys.exit(reason)

    with httpx.Client(base_url=args.server, trust_env=False, timeout=30) as client:
        board = wait_for_board(client, args.device, args.wait)
        source, reason = (args.assets, None) if args.assets else package_assets(board)
        if reason:
            sys.exit(reason)
        image = source.read_bytes()
        read_assets(image)
        old = wake_word_of(image) or {}
        print(f"板子：{board['name']}（{board['id']}，{board['version']}），现在的唤醒词：{board['wake'] or '未知'}")
        print(f"资源包：{source.relative_to(ROOT) if source.is_relative_to(ROOT) else source}"
              f"（里面原来是 {old.get('text', '未知')}）")
        print(f"新唤醒词：{args.text}（{command}）")
        print("接下来板子会" + ("重启，开机下载资源包（屏幕显示进度），下载时不要断电。" if not args.no_reboot
                          else "收到下载地址；你手动重启后下载资源包，下载时不要断电。"))
        if not args.yes and input("确定吗？输入 y 继续：").strip().lower() != "y":
            sys.exit("没有改")
        response = client.post("/gateway/api/wake_word", content=image,
                               params={"device": board["id"], "text": args.text, "command": command,
                                       "reboot": "0" if args.no_reboot else "1"},
                               headers={"Content-Type": "application/octet-stream"})
        result = response.json()
        if response.status_code != 200:
            sys.exit("没改成：" + result.get("error", response.text))
    print(f"已发给板子：{result['url']}（{result['size'] / 1024 / 1024:.1f} MB）")
    if result.get("note"):
        print(result["note"])
    print(f"板子正在重启。下载完成后说「{args.text}」试试；旧唤醒词「{board['wake'] or old.get('text', '')}」应该不再有反应。"
          if result["rebooting"] else "地址已存进板子，手动重启后开始下载。")


if __name__ == "__main__":
    main()
