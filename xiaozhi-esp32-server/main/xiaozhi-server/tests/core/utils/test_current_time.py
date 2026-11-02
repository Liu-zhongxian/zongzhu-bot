"""Tests for core/utils/current_time.py.

把模块里的 datetime 换成 now() 固定的子类，测试不会在午夜前后不稳定，也能验证星期和农历的对应。
（原来用 freezegun，它不在依赖里；pytest 和 unittest 都能跑这一版。）
"""
import unittest
from datetime import datetime
from unittest import mock

from core.utils import current_time


def frozen(text):
    """让 current_time 里的 datetime.now() 固定返回 text 这个时刻"""
    moment = datetime.fromisoformat(text)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    return mock.patch.object(current_time, "datetime", FrozenDatetime)


class CurrentTimeTest(unittest.TestCase):
    def test_get_current_time_format_is_hh_mm(self):
        with frozen("2026-09-02 10:30:00"):
            self.assertEqual(current_time.get_current_time(), "10:30")

    def test_get_current_time_at_late_hour(self):
        with frozen("2026-09-02 23:59:59"):
            self.assertEqual(current_time.get_current_time(), "23:59")

    def test_get_current_date_format_is_iso(self):
        with frozen("2026-09-02 10:30:00"):
            self.assertEqual(current_time.get_current_date(), "2026-09-02")

    def test_get_current_weekday_returns_chinese_label(self):
        with frozen("2026-09-02 10:30:00"):  # 2026-09-02 是星期三
            self.assertEqual(current_time.get_current_weekday(), "星期三")

    def test_weekday_map_has_all_seven_days(self):
        self.assertEqual(set(current_time.WEEKDAY_MAP.keys()), {
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        })

    def test_get_current_time_info_returns_four_tuple(self):
        with frozen("2026-09-02 10:30:00"):
            info = current_time.get_current_time_info()
        self.assertIsInstance(info, tuple)
        self.assertEqual(len(info), 4)
        time_str, date_str, weekday, lunar = info
        self.assertEqual(time_str, "10:30")
        self.assertEqual(date_str, "2026-09-02")
        self.assertEqual(weekday, "星期三")
        self.assertIn("年", lunar)  # 农历里有"年"字

    def test_get_current_lunar_date_contains_year(self):
        """cnlunar 给出的农历里有"年"字"""
        with frozen("2026-09-02 10:30:00"):
            self.assertIn("年", current_time.get_current_lunar_date())


if __name__ == "__main__":
    unittest.main()
