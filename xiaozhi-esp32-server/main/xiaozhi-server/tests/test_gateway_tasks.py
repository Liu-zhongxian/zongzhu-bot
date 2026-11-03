"""G17：网关页面"转交任务"（core/gateway/tasks.py），从 Bot 的回传目录读。"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from core.gateway import tasks

NOW = 1_800_000_000.0


class TasksTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.replies = self.dir / "replies"
        self.replies.mkdir()
        webhook = self.dir / "bot.json"
        webhook.write_text(json.dumps({"url": "https://x", "token": "t", "reply_dir": str(self.replies),
                                       "reply_wait_seconds": 300}))
        self.config = {"grok_bot": {"enabled": True, "config_file": str(webhook)}}

    def request(self, letter, kind, ago, question="问题", reply=None):
        rid = "ESP32-" + letter * 32
        (self.replies / f"{rid}.{kind}.json").write_text(json.dumps(
            {"request_id": rid, "device": "94:a9:90:2d:a3:70", "created": NOW - ago, "question": question},
            ensure_ascii=False))
        if reply:
            path = self.replies / f"{rid}.json"
            path.write_text(json.dumps({"request_id": rid, "text": reply}, ensure_ascii=False))
            os.utime(path, (NOW - ago + 20, NOW - ago + 20))

    def test_each_request_lands_in_its_group(self):
        self.request("a", "pending", 60, "现在几点了")                     # 还在等
        self.request("b", "pending", 120, "查天气", reply="明天晴。")        # 回复到了还没念
        self.request("c", "sent", 600, "一公里多少米", reply="一千米。")      # 念过了
        self.request("d", "pending", 1200, "没回的")                        # 超过等待时限
        self.request("e", "sent", 2 * 24 * 3600, "两天前的", reply="旧的")   # 24 小时以前，不看
        result = tasks.collect(self.config, {"94:a9:90:2d:a3:70": "立创实战派"}, now=NOW)
        self.assertEqual([t["question"] for t in result["running"]], ["现在几点了"])
        self.assertEqual([t["reply"] for t in result["report"]], ["明天晴。"])
        done = result["done"][0]
        self.assertEqual((done["question"], done["reply"], done["board"]), ("一公里多少米", "一千米。", "立创实战派"))
        self.assertEqual(done["replied"] - done["created"], 20)
        self.assertEqual([t["question"] for t in result["timeout"]], ["没回的"])

    def test_follow_up_is_shown_under_the_reply(self):
        self.request("a", "sent", 60, reply="第一次回答。")
        rid = "ESP32-" + "a" * 32
        (self.replies / f"{rid}.more-1.json").write_text(json.dumps({"request_id": rid, "text": "更正。"},
                                                                    ensure_ascii=False))
        self.assertEqual(tasks.collect(self.config, {}, now=NOW)["done"][0]["reply"], "第一次回答。\n更正。")

    def test_no_bot_or_no_reply_dir_shows_nothing(self):
        self.assertIsNone(tasks.collect({}, {}, now=NOW))
        webhook = self.dir / "plain.json"
        webhook.write_text(json.dumps({"url": "https://x", "token": "t"}))
        self.assertIsNone(tasks.collect({"grok_bot": {"enabled": True, "config_file": str(webhook)}}, {}, now=NOW))


if __name__ == "__main__":
    unittest.main()
