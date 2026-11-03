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


# G8b step 5: wake words and call names set on this page (core/gateway/settings.py), in effect at once
SETTING_ACTIONS = {"set_speaker_wake_words", "set_call_names", "set_auto_firmware", "check_releases"}


def settings_view(config) -> dict:
    """What the page shows and edits."""
    from core import gateway
    from core.gateway.xiaoai import control as speaker_control, server as speaker_server

    server = speaker_control.server
    names = gateway.agent_call_names(config)
    from core.gateway import releases

    return {
        "releases": {"source": releases.source(config) is not None, "auto": releases.auto_update(),
                     "checked_at": releases.state["checked_at"], "result": releases.state["result"]},
        "speaker": server is not None,
        "speaker_wake_words": speaker_server.wake_words(config),
        "skipped": list(server.skipped) if server else [],
        "call_names": [{"agent": name, "label": gateway.AGENTS[name].label(config),
                        "names": [names[name]] if isinstance(names[name], str) else list(names[name] or [])}
                       for name in names],
    }


async def settings_action(config, action, value) -> dict:
    from core import gateway
    from core.gateway import settings
    from core.gateway.xiaoai import control as speaker_control

    if action in ("set_auto_firmware", "check_releases"):
        from core.gateway import releases

        if action == "set_auto_firmware":
            settings.put("auto_firmware", value in (True, "on", "1", 1))
            return {"message": "自动更新项目发布的固件：" + ("开" if releases.auto_update() else "关")}
        return {"message": await releases.run_check(config)}
    try:
        if action == "set_speaker_wake_words":
            words = settings.words(value)
            settings.put("speaker_wake_words", words)
            message = f"音箱唤醒词改成：{'、'.join(words)}。"
        else:
            agent = (value or {}).get("agent") if isinstance(value, dict) else None
            if agent not in gateway.agent_call_names(config):
                raise ControlError("没有这个 AI")
            words = settings.words((value or {}).get("names", ""), allow_empty=True)
            saved = settings.get("call_names") or {}
            saved[agent] = words
            settings.put("call_names", saved)
            label = gateway.AGENTS[agent].label(config)
            message = f"{label} 的呼名改成：{'、'.join(words)}。" if words else f"{label} 不再能用名字叫。"
    except settings.SettingError as e:
        raise ControlError(str(e)) from None
    server = speaker_control.server
    if server:
        # 呼名也是音箱的唤醒词，两种改动都要重载音箱的唤醒词识别
        _, skipped = await server.reload()
        if skipped:
            message += f"唤醒词模型认不了这些，音箱不会被它们唤醒：{'、'.join(skipped)}。"
    return {"message": message}


async def board_wake_word(config, conn, text) -> dict:
    """G8b step 5: a new wake word for this board, from the page. Same as tools/wake_word.py: the
    resource package of the board's firmware version gets the new word, the board reboots and downloads it."""
    from core.gateway import wake_assets

    text = str(text or "").strip()
    command = wake_assets.pinyin_command(text) if text else ""
    reason = wake_assets.check_wake_word(text, command)
    if reason:
        raise ControlError(reason)
    board = status._boards.get(conn.device_id, {})
    source, reason = wake_assets.package_assets(wake_assets.firmware_root(config), board.get("type", ""),
                                                board.get("version", ""))
    if reason:
        raise ControlError(reason)
    try:
        image = await asyncio.to_thread(source.read_bytes)
        result = await wake_assets.change_wake_word(conn, image, text, command, reboot=True)
    except (ValueError, RuntimeError) as e:
        raise ControlError(f"没改成：{e}") from None
    status.note_new_wake_word(conn.device_id, text)
    return {"message": f"板子正在重启，开机下载资源包（约 {result['size'] / 1024 / 1024:.1f} MB，屏幕显示进度，"
                       f"下载时不要断电）。之后说「{text}」唤醒。" + (result.get("note") or "")}
