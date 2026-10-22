"""Plays songs on this Mac: a go-music-dl service for search and audio, mpv for playback.

Both programs are started on first use and stopped when the server exits. mpv
runs idle in the background and is driven over its JSON IPC socket, so pause,
resume and track changes are ours rather than a music app's.

go-music-dl listens on every interface (it has no bind-address option), so the
port is reachable from the LAN while the server runs.
"""

import atexit
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

from core.music.source import SEPARATORS, GoMusicDL, Song

# macOS limits a Unix socket path to 104 bytes; a longer one makes mpv skip the
# socket silently and leaves an uncontrollable player behind (2026-10-22).
SOCKET_PATH_MAX = 100
DUCK_VOLUME = 25
DUCK_SECONDS = 15


class MusicError(Exception):
    """Shown to the user as the spoken reason."""


def _wait(check, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


class Service:
    """The go-music-dl web service; reuses one already listening on the port."""

    def __init__(self, binary: str, port: int):
        # Absolute: Popen(cwd=...) would look a relative program up from the new directory
        self.binary = Path(binary).expanduser().resolve()
        self.port = int(port)
        self.base = f"http://127.0.0.1:{self.port}/music"
        self.proc: Optional[subprocess.Popen] = None

    def alive(self) -> bool:
        try:
            with urllib.request.urlopen(self.base + "/", timeout=2) as r:
                return r.status == 200
        except OSError:
            return False

    def ensure(self) -> None:
        if self.alive():
            return
        if not self.binary.is_file():
            raise MusicError("电脑上没有找到音乐服务程序，请检查配置。")
        log = open(self.binary.parent / "service.log", "ab")
        # Its data directory (settings, login cookies) is relative to the working directory.
        self.proc = subprocess.Popen([str(self.binary), "web", "--no-browser", "--port", str(self.port)],
                                     cwd=self.binary.parent, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
        log.close()
        if not _wait(self.alive, 10):
            self.stop()
            raise MusicError("音乐服务没能启动，请看电脑上的日志。")

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.kill()


class Mpv:
    def __init__(self, binary: str, socket_path: str):
        self.binary = Path(binary).expanduser().resolve()
        # Kept as written (relative to the server directory) so it stays under the length limit
        self.socket_path = str(socket_path)
        self.proc: Optional[subprocess.Popen] = None
        self._request = 0
        self._lock = threading.Lock()

    def _connect(self) -> socket.socket:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(self.socket_path)
        return s

    def alive(self) -> bool:
        try:
            self._connect().close()
            return True
        except OSError:
            return False

    def ensure(self) -> None:
        if self.alive():
            return
        if len(self.socket_path.encode()) > SOCKET_PATH_MAX:
            raise MusicError("播放器的控制文件路径太长，请在配置里换一个短路径。")
        if not self.binary.is_file():
            raise MusicError("电脑上没有找到播放器，请检查配置。")
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)  # stale socket from a player that is gone
        self.proc = subprocess.Popen(
            [str(self.binary), "--idle=yes", "--no-video", "--no-terminal", "--volume=100",
             f"--input-ipc-server={self.socket_path}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        if not _wait(self.alive, 5):
            self.stop()
            raise MusicError("播放器没能启动。")

    def command(self, *args):
        """Send one mpv command and return its data; raises MusicError on failure."""
        with self._lock:
            self._request += 1
            rid = self._request
            try:
                with self._connect() as s:
                    s.sendall((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
                    f = s.makefile("rb")
                    while True:
                        line = f.readline()
                        if not line:
                            raise MusicError("播放器没有响应。")
                        reply = json.loads(line)
                        if reply.get("request_id") == rid:
                            break
            except (OSError, ValueError) as error:
                raise MusicError("播放器没有响应。") from error
        if reply.get("error") not in (None, "success"):
            if args[0] == "get_property":
                return None  # e.g. no file loaded
            raise MusicError("播放器执行失败。")
        return reply.get("data")

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            try:
                self.command("quit")
                proc.wait(2)
            except (MusicError, subprocess.TimeoutExpired):
                proc.kill()


def system_volume() -> int:
    out = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                         capture_output=True, text=True, timeout=5)
    try:
        return int(out.stdout.strip())
    except ValueError:
        raise MusicError("读不到电脑的音量。")


def set_system_volume(level: int) -> int:
    level = max(0, min(100, int(level)))
    subprocess.run(["osascript", "-e", f"set volume output volume {level} without output muted"],
                   capture_output=True, timeout=5)
    return level


def set_muted(muted: bool) -> None:
    subprocess.run(["osascript", "-e", f"set volume output muted {'true' if muted else 'false'}"],
                   capture_output=True, timeout=5)


class Music:
    """What is playing and what was played. One per server: the Mac has one speaker."""

    def __init__(self, config: dict):
        self.service = Service(config["go_music_dl"], config.get("port", 18080))
        self.source = GoMusicDL(self.service.base)
        self.mpv = Mpv(config["mpv"], config["socket"])
        self.current: Optional[Song] = None
        self.last_why = ""
        self.history: List[Song] = []  # played songs, for "上一首"
        self._duck_timer: Optional[threading.Timer] = None
        self._lock = threading.RLock()

    # Searching and playing

    def play(self, song: Song) -> Song:
        with self._lock:
            self.mpv.ensure()
            self.mpv.command("set_property", "loop-file", "no")
            self.mpv.command("loadfile", self.source.stream_url(song), "replace")
            self.mpv.command("set_property", "pause", False)
            self._restore_volume()
            if self.current and self.current != song:
                self.history.append(self.current)
                del self.history[:-50]
            self.current = song
            return song

    def find_and_play(self, title: Optional[str], artist: Optional[str]) -> Optional[Song]:
        """Plays the song; `last_why` says how it was chosen or why nothing was."""
        self.service.ensure()
        if title:
            song, self.last_why = self.source.find(title, artist)
        else:
            song = self.source.by_artist(artist)
            self.last_why = "" if song else "各平台都没找到这位歌手"
        return self.play(song) if song else None

    def next(self) -> Optional[Song]:
        if not self.current:
            return None
        self.service.ensure()
        played = [s.name for s in self.history] + [self.current.name]
        artist = SEPARATORS.split(self.current.artist)[0].strip() or self.current.artist
        song = self.source.by_artist(artist, exclude=played)
        return self.play(song) if song else None

    def previous(self) -> Optional[Song]:
        with self._lock:
            if not self.history:
                return None
            song = self.history.pop()
            current, self.current = self.current, None  # keep "上一首" from pushing it back
            self.play(song)
            if current:
                self.history.append(current)
            return song

    # Transport

    def playing(self) -> bool:
        return bool(self.current) and self.mpv.alive() and self.mpv.command("get_property", "pause") is False \
            and self.mpv.command("get_property", "idle-active") is False

    def paused(self) -> bool:
        return bool(self.current) and self.mpv.alive() and self.mpv.command("get_property", "pause") is True

    def pause(self) -> None:
        self.mpv.command("set_property", "pause", True)

    def resume(self) -> None:
        self._restore_volume()
        self.mpv.command("set_property", "pause", False)

    def seek(self, seconds: float, absolute: bool = False) -> None:
        self.mpv.command("seek", seconds, "absolute" if absolute else "relative")
        self.mpv.command("set_property", "pause", False)

    def loop(self, on: bool) -> None:
        self.mpv.command("set_property", "loop-file", "inf" if on else "no")

    def stop(self) -> None:
        with self._lock:
            if self.mpv.alive():
                self.mpv.command("stop")
            if self.current:
                self.history.append(self.current)
            self.current = None

    # Lowering the music while the board listens

    def duck(self) -> None:
        """Lower the music so the board's microphone hears the user; restores itself."""
        if not self.current or not self.mpv.alive():
            return
        try:
            self.mpv.command("set_property", "volume", DUCK_VOLUME)
        except MusicError:
            return
        if self._duck_timer:
            self._duck_timer.cancel()
        self._duck_timer = threading.Timer(DUCK_SECONDS, self._restore_volume)
        self._duck_timer.daemon = True
        self._duck_timer.start()

    def _restore_volume(self) -> None:
        if self._duck_timer:
            self._duck_timer.cancel()
            self._duck_timer = None
        if self.mpv.alive():
            try:
                self.mpv.command("set_property", "volume", 100)
            except MusicError:
                pass

    def unduck(self) -> None:
        if self._duck_timer:
            self._restore_volume()

    def close(self) -> None:
        if self._duck_timer:
            self._duck_timer.cancel()
        self.mpv.stop()
        self.service.stop()


_music: Optional[Music] = None
_music_lock = threading.Lock()


def get_music(config: dict) -> Music:
    global _music
    with _music_lock:
        if _music is None:
            _music = Music(config)
            atexit.register(_music.close)
        return _music


def current_music() -> Optional[Music]:
    """The player if it was ever used, without starting anything."""
    return _music
