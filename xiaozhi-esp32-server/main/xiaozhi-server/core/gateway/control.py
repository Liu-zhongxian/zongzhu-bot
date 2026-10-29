"""G18b：在网关页面上改东西。默认打开页面就能改；配置里写了 gateway.password 时，
打开页面先输一次口令，浏览器记住，之后直接点（2026-10-30 你定：口令可选，默认不设）。

板子的设置走板子上的 MCP 工具，只有板子醒着、连着时能改；点歌控制的是这台 Mac 上的播放器和系统音量
（歌在 Mac 上放，core/gateway/skills/music/player.py），板子待机也能用。
"""
import asyncio
import hashlib
import hmac

from core.gateway import board_info, board_tools, status

# action -> (tool, argument name or None, how the board may answer)
BOARD_ACTIONS = {
    "volume": ("self.audio_speaker.set_volume", "volume"),
    "brightness": ("self.screen.set_brightness", "brightness"),
    "theme": ("self.screen.set_theme", "theme"),
    "reboot": ("self.reboot", None),
    "wifi_config": ("self.system.reconfigure_wifi", None),
}
# The board drops the connection right after these, often before answering (2026-10-30).
LEAVING = {"reboot": "板子正在重启，十几秒后会自己连回来。",
           "wifi_config": "板子已进入配网模式：用手机连它的配网热点（名字在板子屏幕上），在热点页面里选新的 WiFi。"}
MUSIC_ACTIONS = {"music_previous", "music_pause", "music_resume", "music_next", "music_stop", "mac_volume"}


class ControlError(Exception):
    pass


def _password(config):
    return str((config.get("gateway") or {}).get("password") or "")


def password_required(config) -> bool:
    return bool(_password(config))


def token_for(config, password: str) -> str:
    """What the browser keeps instead of the password; changes when the password or server.auth_key does."""
    key = str((config.get("server") or {}).get("auth_key") or "").encode()
    return hmac.new(key, ("gateway:" + password).encode(), hashlib.sha256).hexdigest()


def login(config, password: str):
    """The token for a right password, None otherwise."""
    expected = _password(config)
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        return None
    return token_for(config, expected)


def allowed(config, token: str) -> bool:
    if not password_required(config):
        return True
    return hmac.compare_digest((token or "").encode(), token_for(config, _password(config)).encode())


def _value(action, value):
    if action in ("volume", "brightness", "mac_volume"):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ControlError("要填 0–100 的数") from None
        if not 0 <= value <= 100:
            raise ControlError("要填 0–100 的数")
    if action == "theme" and value not in ("light", "dark"):
        raise ControlError("主题只能是 light 或 dark")
    return value


async def board_action(conn, action, value=None) -> dict:
    tool, argument = BOARD_ACTIONS[action]
    value = _value(action, value)
    try:
        result = await board_tools.call_board_tool(conn, tool, {argument: value} if argument else {}, timeout=5)
    except RuntimeError as e:
        if action in LEAVING and "没有回应" in str(e):
            return {"message": LEAVING[action]}
        raise ControlError(str(e)) from None
    if action == "theme" and board_tools.tool_json(result) is False:
        raise ControlError("板子没有这个主题")
    if action in LEAVING:
        return {"message": LEAVING[action]}
    try:  # show the new value right away instead of after the next minute's read
        status.note_info(conn.device_id, await board_info.read(conn))
    except RuntimeError:
        pass
    return {"message": "已改好。"}


def _music_action(action, value):
    from core.gateway.skills.music.player import MusicError, current_music, set_system_volume

    try:
        if action == "mac_volume":
            return f"电脑音量调到 {set_system_volume(value)}。"
        music = current_music()
        if music is None or (action != "music_previous" and not music.current):
            raise ControlError("现在没有在放歌：先对板子说一句点歌，比如“放周杰伦的晴天”。")
        if action == "music_pause":
            music.pause()
            return "已暂停。"
        if action == "music_resume":
            music.resume()
            return "继续播放。"
        if action == "music_stop":
            music.stop()
            return "已停止播放。"
        song = music.next() if action == "music_next" else music.previous()
        if song is None:
            raise ControlError("没有下一首了。" if action == "music_next" else "没有上一首了。")
        return f"正在播放：{song.artist}的{song.name}。"
    except MusicError as e:
        raise ControlError(str(e)) from None


async def music_action(action, value=None) -> dict:
    value = _value(action, value)
    return {"message": await asyncio.to_thread(_music_action, action, value)}


def music_status() -> dict:
    """Now playing and the Mac's volume, for the page; never starts the player. Blocking (osascript, mpv)."""
    from core.gateway.skills.music.player import current_music, system_volume

    try:
        volume = system_volume()
    except Exception:  # osascript failed; the page is only a view
        volume = None
    music = current_music()
    song = music.current if music else None
    if song is None:
        return {"state": "stopped", "mac_volume": volume}
    try:
        state = "playing" if music.playing() else "paused" if music.paused() else "stopped"
    except Exception:  # mpv went away
        state = "stopped"
    return {"state": state, "title": song.name, "artist": song.artist, "mac_volume": volume}
