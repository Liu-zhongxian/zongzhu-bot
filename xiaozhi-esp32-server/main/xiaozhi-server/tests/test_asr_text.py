import unittest

from core.utils import asr_text


class TidyTest(unittest.TestCase):
    def test_removes_spaces_around_chinese_punctuation(self):
        self.assertEqual(asr_text.tidy("你好， 宗主， 帮我找一下 X 上面"), "你好，宗主，帮我找一下 X 上面")

    def test_joins_spelled_letters(self):
        self.assertEqual(asr_text.tidy("提一个 P R 吧"), "提一个 PR 吧")

    def test_keeps_normal_english(self):
        self.assertEqual(asr_text.tidy("I am OK, run npm install"), "I am OK, run npm install")


class CorrectionTest(unittest.TestCase):
    def test_wake_word_variants_from_logs(self):
        for text in ["你好，中国。", "你好，中主。", "你好，钟主。", "你好，宗猪。", "个你好，中猪公。"]:
            self.assertIn("你好宗主", asr_text.fix_asr_result(text, {}), text)

    def test_ordinary_words_untouched(self):
        self.assertEqual(asr_text.fix_asr_result("中国很大", {}), "中国很大")

    def test_english_whole_word_case_insensitive(self):
        self.assertEqual(asr_text.fix_asr_result("查一下 Clock Code 的版本", {}), "查一下 Claude Code 的版本")
        self.assertEqual(asr_text.fix_asr_result("cloud coder", {}), "cloud coder")

    def test_config_overrides_defaults(self):
        config = {"asr_corrections": {"MCP": ["MCT"]}}
        self.assertEqual(asr_text.fix_asr_result("你好，中主", config), "你好，中主")
        self.assertEqual(asr_text.fix_asr_result("做一个MCT工具", config), "做一个MCP工具")

    def test_funasr_dict_result(self):
        result = asr_text.fix_asr_result({"content": "你好，钟主。", "language": "zh"}, {})
        self.assertEqual(result, {"content": "你好宗主。", "language": "zh"})

    def test_empty(self):
        self.assertEqual(asr_text.fix_asr_result("", {}), "")
        self.assertEqual(asr_text.fix_asr_result({"content": ""}, {}), {"content": ""})


class HotwordTest(unittest.TestCase):
    def test_default_and_override(self):
        self.assertIn("宗主", asr_text.hotwords_of({}))
        self.assertEqual(asr_text.hotwords_of({"asr_hotwords": ["Grok", " "]}), ["Grok"])


if __name__ == "__main__":
    unittest.main()
