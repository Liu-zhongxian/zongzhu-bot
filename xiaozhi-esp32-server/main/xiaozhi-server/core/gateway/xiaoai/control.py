"""网关页面上控制小米音箱（G19d 第 2 步）：音量、播放 / 暂停、"说一句话"、打断小爱。

每个操作在音箱上跑一条固定的命令（经 Client 的 run_shell），页面只能传数字（音量）或要念的文字，
文字不进命令行：用后端的 TTS 合成，再当成声音发给音箱。命令来自音箱上的 mphelper 和
open-xiaoai 的 SpeakerManager（2026-11-02 在音箱上只读查过 `ubus -v list mediaplayer`）：
- 音量：mediaplayer player_set_volume（0–100）
- 播放 / 暂停：mediaplayer player_play_operation（media common，和 mphelper play / pause 一样），一个按钮切换
- 打断小爱：照原来 bridge 的 stop_device_audio（实机用过）：结束念 TTS 的 tts_play.sh 和放音频的 miplayer、
  mphelper pause，再让小爱退出聆听（pnshelper event_notify）。2026-11-02 先用的是重启对话服务
  mico_aivs_lab（open-xiaoai 的 abort_xiaoai），小爱说话时点了没反应：已经在放的声音不会停
"""
import asyncio

from config.logger import setup_logging
from core.gateway.control import ControlError
from core.gateway import status
from core.gateway.xiaoai import info, prompts

ACTIONS = {"speaker_volume", "speaker_play", "speaker_pause", "speaker_say", "speaker_stop_xiaoai"}
STOP_XIAOAI = ("killall tts_play.sh miplayer 2>/dev/null; mphelper pause; "
               "ubus call pnshelper event_notify '{\"src\":3,\"event\":7}'; sleep 0.1; "
               "ubus call pnshelper event_notify '{\"src\":3,\"event\":8}'")
TAG = __name__
logger = setup_logging()
SAY_MAX = 100  # "说一句话"最多这么多字

# device id -> (SpeakerLink, SpeakerDevice)：连着的音箱，server.py 连上时登记、断开时去掉
speakers: dict = {}
server = None  # XiaoaiServer：网关页面上改了唤醒词、呼名时让它重载（server.py 设）


def _find(device):
    device = (device or "").strip().lower()
    found = [k for k in speakers if device and k.lower().endswith(device)]
    if len(found) != 1:
        raise ControlError("音箱没连着后端：等它连上（开机后约 20 秒）再点" if not found else "有好几台音箱对得上")
    return found[0], speakers[found[0]]


async def _run(link, command, check=True):
    result = await link.call("run_shell", command, timeout=10) or {}
    output = (result.get("stderr") or result.get("stdout") or "").strip()
    logger.bind(tag=TAG).info(f"网关控制音箱：{command[:60]} → 退出码 {result.get('exit_code')} {output[:120]}")
    if check and (result.get("exit_code") not in (0, None) or '"code": -' in result.get("stdout", "")):
        raise ControlError(f"音箱没执行成功：{output[:80]}")
    return result


async def act(config, device, action, value):
    device_id, (link, speaker) = _find(device)
    if action == "speaker_volume":
        try:
            volume = int(value)
        except (TypeError, ValueError):
            raise ControlError("要填 0–100 的数") from None
        if not 0 <= volume <= 100:
            raise ControlError("要填 0–100 的数")
        await _run(link, f"ubus call mediaplayer player_set_volume '{{\"volume\":{volume}}}'")
        message = f"音箱音量调到 {volume}。"
    elif action in ("speaker_play", "speaker_pause"):
        verb = "play" if action == "speaker_play" else "pause"
        await _run(link, f"ubus call mediaplayer player_play_operation '{{\"action\":\"{verb}\",\"media\":\"common\"}}'")
        # 按钮马上换过来；音箱的 playing 事件随后也会到
        status.note_speaker_play(device_id, "playing" if verb == "play" else "paused")
        message = "音箱继续播放。" if verb == "play" else "音箱暂停了。"
    elif action == "speaker_stop_xiaoai":
        # killall 没有在跑的程序时退出码不是 0，不算失败
        await _run(link, STOP_XIAOAI, check=False)
        message = "已打断小爱。"
    elif action == "speaker_say":
        text = str(value or "").strip()
        if not text:
            raise ControlError("先填要说的话")
        if len(text) > SAY_MAX:
            raise ControlError(f"最多 {SAY_MAX} 个字")
        try:
            pcm = await prompts.speech(config, text)
        except Exception as e:
            raise ControlError(f"合成语音失败：{type(e).__name__}") from None
        await speaker.interrupt()  # 正在说别的就先停下
        speaker.player.add(pcm)
        message = f"音箱在念：{text}"
    else:
        raise ControlError(f"不认识的操作 {action}")
    # 音量这些马上重读一次，不用等定时读；在后台读，不让页面等（读一次要在音箱上再跑一条命令）
    asyncio.create_task(_refresh(link, device_id))
    return {"message": message}


async def _refresh(link, device_id):
    try:
        status.note_info(device_id, {"speaker": await info.read(link)})
    except Exception:
        pass
