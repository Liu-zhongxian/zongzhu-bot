"""G17：网关页面总览上的模块状态（core/gateway/modules.py）。只看，不启动任何东西。"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from core.gateway import modules
from core.gateway.xiaoai import control as speaker_control


def by_name(result):
    return {m["kind"]: m for m in result}


class ModulesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        patcher = mock.patch.object(speaker_control, "server", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_switched_off_modules_are_grey(self):
        found = by_name(modules.collect({}))
        self.assertEqual(found["本机技能"]["state"], "off")
        self.assertEqual(found["AI（Webhook）"]["state"], "off")
        self.assertEqual(found["设备接入（4399）"]["state"], "off")

    def test_music_missing_programs_is_red_and_not_running_is_yellow(self):
        config = {"local_music": {"enabled": True, "go_music_dl": str(self.dir / "nope"), "mpv": str(self.dir / "nope2"),
                                  "socket": str(self.dir / "s.sock")}}
        self.assertEqual(by_name(modules.collect(config))["本机技能"]["state"], "bad")
        for name in ("dl", "mpv"):
            (self.dir / name).write_bytes(b"")
        config["local_music"].update(go_music_dl=str(self.dir / "dl"), mpv=str(self.dir / "mpv"))
        with mock.patch("core.gateway.skills.music.player.Service.alive", return_value=False), \
                mock.patch("core.gateway.skills.music.player.Mpv.alive", return_value=False):
            music = by_name(modules.collect(config))["本机技能"]
        self.assertEqual(music["state"], "warn")
        self.assertIn("自动启动", music["detail"])

    def test_bot_shows_its_last_reply_and_never_its_token(self):
        reply_dir = self.dir / "replies"
        reply_dir.mkdir()
        (reply_dir / ("ESP32-" + "a" * 32 + ".json")).write_text("{}")
        os.utime(reply_dir / ("ESP32-" + "a" * 32 + ".json"), (time.time() - 120, time.time() - 120))
        (reply_dir / ("ESP32-" + "b" * 32 + ".pending.json")).write_text("{}")
        old = reply_dir / ("ESP32-" + "c" * 32 + ".pending.json")  # 一小时前的，没等到，不算在等
        old.write_text("{}")
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        webhook = self.dir / "bot.json"
        webhook.write_text(json.dumps({"url": "https://x", "token": "SECRET", "reply_dir": str(reply_dir)}))
        bot = by_name(modules.collect({"grok_bot": {"enabled": True, "config_file": str(webhook)}}))["AI（Webhook）"]
        self.assertEqual(bot["state"], "ok")
        self.assertIn("上次回复 2 分钟前", bot["detail"])
        self.assertIn("1 个请求等回复", bot["detail"])
        self.assertNotIn("SECRET", json.dumps(bot, ensure_ascii=False))
        broken = by_name(modules.collect({"grok_bot": {"enabled": True, "config_file": str(self.dir / "no")}}))
        self.assertEqual(broken["AI（Webhook）"]["state"], "bad")

    def test_speaker_without_wake_word_model_is_red(self):
        config = {"gateway": {"xiaoai": {"enabled": True}}}
        self.assertEqual(by_name(modules.collect(config))["设备接入（4399）"]["state"], "bad")
        with mock.patch.object(speaker_control, "server", mock.Mock(spotter=object(), wake_words=["宗主", "bot"])), \
                mock.patch.dict(speaker_control.speakers, {"aa:bb": (None, None)}, clear=True):
            speaker = by_name(modules.collect(config))["设备接入（4399）"]
        self.assertEqual(speaker["state"], "ok")
        self.assertIn("宗主、bot", speaker["detail"])

    def test_results_are_cached(self):
        with mock.patch.object(modules, "collect", return_value=[{"name": "x"}]) as collect, \
                mock.patch.dict(modules._cache, {"at": 0.0, "modules": []}):
            modules.cached({})
            modules.cached({})
        collect.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class FlowTest(unittest.TestCase):
    """G17：工作原理页按配置画（core/gateway/flow.py）。"""

    def test_drawn_from_the_config(self):
        from core.gateway import flow
        config = {"selected_module": {"VAD": "SileroVAD", "ASR": "SherpaXASR", "TTS": "EdgeTTS"},
                  "VAD": {"SileroVAD": {"min_silence_duration_ms": 1000}},
                  "ASR": {"SherpaXASR": {"type": "sherpa_onnx_local"}},
                  "TTS": {"EdgeTTS": {"type": "edge", "voice": "zh-CN-XiaoxiaoNeural"}},
                  "grok_bot": {"enabled": True, "bot_name": "硬件"},
                  "gateway": {"skills": [], "call_names": {"grok_bot": ["bot"]}}}
        with mock.patch("core.gateway.settings.get", return_value=None):
            view = flow.view(config)
        steps = {s["name"]: s for s in view["steps"]}
        self.assertEqual(steps["收音"]["note"], "静音 1 秒算说完")
        self.assertEqual(steps["识别"]["value"], "SherpaXASR")
        self.assertIn("zh-CN-XiaoxiaoNeural", steps["合成和播放"]["note"])
        self.assertEqual(view["skills"], [])  # 没开本机技能
        self.assertEqual(view["calls"], [{"agent": "Grok Bot · 硬件", "names": ["bot"]}])
        self.assertEqual(view["agent"], "Grok Bot · 硬件")
        self.assertFalse(view["speaker"]["on"])
