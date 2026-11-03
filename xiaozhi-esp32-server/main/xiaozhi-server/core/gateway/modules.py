"""G17：网关页面总览上的"模块"：每个技能和 AI 开没开、能不能用。只看，不启动任何东西。

state：ok 能用；warn 开着但现在没在运行（用到时会自己启动）或有小问题；bad 开着但用不了，要处理；
off 没开。查一次要连 go-music-dl 的网页、读 Bot 的配置文件这些，结果存 CACHE_SECONDS 秒。
不显示 Key、token、Webhook 地址。
"""
import json
import time
from pathlib import Path

CACHE_SECONDS = 10
_cache = {"at": 0.0, "modules": []}


def _ago(seconds):
    if seconds < 60:
        return f"{int(seconds)} 秒前"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    return f"{int(seconds // 86400)} 天前"


def _module(name, kind, state, detail):
    return {"name": name, "kind": kind, "state": state, "detail": detail}


def _music(config):
    from core.gateway import active_skills
    from core.gateway.skills.music.player import Mpv, Service

    music = config.get("local_music") or {}
    if not music.get("enabled") or "local_music" not in [s.name for s in active_skills(config)]:
        return _module("本机点歌", "本机技能", "off", "没开")
    service = Service(music.get("go_music_dl", ""), music.get("port", 18080))
    mpv = Mpv(music.get("mpv", ""), music.get("socket", ""))
    missing = [label for label, path in (("go-music-dl", service.binary), ("mpv", mpv.binary)) if not path.is_file()]
    if missing:
        return _module("本机点歌", "本机技能", "bad", f"找不到 {'、'.join(missing)}，检查配置里的路径")
    running = [label for label, alive in (("go-music-dl", service.alive()), ("mpv", mpv.alive())) if alive]
    if len(running) == 2:
        return _module("本机点歌", "本机技能", "ok", "go-music-dl、mpv 在运行")
    return _module("本机点歌", "本机技能", "warn",
                   (f"{'、'.join(running)} 在运行，" if running else "") + "其余没在运行（有人点歌时自动启动）")


def _grok(config, now):
    from core.gateway import AGENTS

    agent = AGENTS.get("grok_bot")
    name = agent.label(config) if agent else "Grok Bot"
    bot = config.get("grok_bot") or {}
    if not bot.get("enabled"):
        return _module(name, "AI（Webhook）", "off", "没开")
    try:
        webhook = json.loads(Path(bot.get("config_file", "")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _module(name, "AI（Webhook）", "bad", "读不到 Bot 的配置文件（grok_bot.config_file）")
    if not webhook.get("url") or not webhook.get("token"):
        return _module(name, "AI（Webhook）", "bad", "Bot 的配置文件里缺 Webhook 地址或 token")
    reply_dir = Path(webhook.get("reply_dir") or "")
    if not webhook.get("reply_dir"):
        return _module(name, "AI（Webhook）", "ok", "能提交；没配回传目录，回复只在 Grok 对话里")
    if not reply_dir.is_dir():
        return _module(name, "AI（Webhook）", "warn", "回传目录还没有（第一次提交时建）")
    replies = [p for p in reply_dir.glob("ESP32-*.json")
               if not p.name.endswith((".pending.json", ".sent.json")) and ".more-" not in p.name]
    # 还在等的：提交后 reply_wait_seconds 以内（和板子显示等待用的同一个时限）；更早的没等到，不算
    from core.handle.grokBotReply import REPLY_WAIT_SECONDS

    wait = webhook.get("reply_wait_seconds", REPLY_WAIT_SECONDS)
    waiting = sum(1 for p in reply_dir.glob("ESP32-*.pending.json") if 0 <= now - p.stat().st_mtime < wait)
    last = max((p.stat().st_mtime for p in replies), default=None)
    detail = f"上次回复 {_ago(now - last)}" if last else "还没收到过回复"
    return _module(name, "AI（Webhook）", "ok", detail + (f" · {waiting} 个请求等回复" if waiting else ""))


def _speaker(config):
    from core.gateway.xiaoai import control as speaker_control

    xiaoai = (config.get("gateway") or {}).get("xiaoai") or {}
    if not xiaoai.get("enabled"):
        return _module("小米音箱接入", "设备接入（4399）", "off", "没开")
    server = speaker_control.server
    if server is None or server.spotter is None:
        return _module("小米音箱接入", "设备接入（4399）", "bad", "唤醒词识别没启动（模型或 token 文件，看后端日志）")
    connected = len(speaker_control.speakers)
    return _module("小米音箱接入", "设备接入（4399）", "ok" if connected else "warn",
                   (f"{connected} 台音箱连着" if connected else "没有音箱连着（音箱开机后约 20 秒自己连上）")
                   + f" · 唤醒词 {'、'.join(server.wake_words)}")


def _selected(config, kind, label):
    name = (config.get("selected_module") or {}).get(kind) or ""
    if not name:
        return _module(label, kind, "off", "没选")
    settings = (config.get(kind) or {}).get(name) or {}
    voice = settings.get("voice") or settings.get("private_voice") or ""
    return _module(name, label, "ok", f"类型 {settings.get('type') or name}" + (f" · 声音 {voice}" if voice else ""))


def collect(config, now=None) -> list:
    """All modules, checked now (blocking: a few local HTTP and file checks)."""
    now = time.time() if now is None else now
    result = []
    for check in (_music, lambda c: _grok(c, now), _speaker):
        try:
            result.append(check(config))
        except Exception as e:  # a broken check must not break the page
            result.append(_module("（检查出错）", "", "bad", f"{type(e).__name__}"))
    result.append(_selected(config, "ASR", "语音识别"))
    result.append(_selected(config, "TTS", "语音合成"))
    return result


def cached(config) -> list:
    if time.monotonic() - _cache["at"] > CACHE_SECONDS:
        _cache["modules"], _cache["at"] = collect(config), time.monotonic()
    return _cache["modules"]
