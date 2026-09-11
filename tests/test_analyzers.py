# -*- coding: utf-8 -*-
"""Analyzers: noise filtering, rhetoric detectors, style metrics, dialogue."""
from __future__ import annotations

import unittest

from author_persona_skill.analyzers.dialogue_analyzer import DialogueAnalyzer, normalize_speaker_name
from author_persona_skill.analyzers.noise import filter_noise
from author_persona_skill.analyzers.rhetoric import count_similes, find_simile_sentences, is_simile_sentence
from author_persona_skill.analyzers.style_analyzer import StyleAnalyzer

from tests import _fixtures as fx


class NoiseTest(unittest.TestCase):

    def test_platform_notes_and_dividers_are_removed(self):
        raw = "正文第一句。\n\n=== ===== ===\n\n求月票：请投我一票\n\n正文第二句。\n\nhttp://example.com/x\n"
        clean, ratio, stats = filter_noise(raw)
        self.assertIn("正文第一句。", clean)
        self.assertIn("正文第二句。", clean)
        self.assertNotIn("求月票", clean)
        self.assertNotIn("example.com", clean)
        self.assertGreater(ratio, 0.0)
        self.assertIn("noise_ratio_pct", stats)

    def test_empty_input_is_safe(self):
        clean, ratio, stats = filter_noise("")
        self.assertEqual(clean, "")
        self.assertEqual(ratio, 0.0)
        self.assertEqual(stats["raw_chars"], 0)


class RhetoricTest(unittest.TestCase):

    def test_explicit_markers_count_but_grammaticalised_ru_does_not(self):
        self.assertTrue(is_simile_sentence("她的手指宛如冰锥。"))
        self.assertTrue(is_simile_sentence("他像一头困兽。"))
        self.assertFalse(is_simile_sentence("如果他来，我就走。"))
        self.assertFalse(is_simile_sentence("例如这样写不行。"))

    def test_simile_sentences_respect_length_window(self):
        long_sentence = "他的话" + "很长" * 60 + "宛如一条河。"
        self.assertEqual(find_simile_sentences(long_sentence), [])
        self.assertEqual(count_similes("她的手指宛如冰锥。他转身离开。"), 1)

    def test_ru_with_measure_word_is_a_simile_but_idioms_are_not(self):
        """校准回归：如一 + 量词是真比喻；如一 + 成语尾巴不是。

        旧规则把"一"整类当成语法化用法排除，漏计了"如一柄长刀"这类句子，
        而比喻密度是核心审计指标（漏计会压低报告数值与证据可选范围）。
        """
        for sentence in ("那道光如一柄长刀劈开夜色。", "他的心跳如一道鼓点。",
                         "如一丝暖意拂过心头。", "那光如一点星光落下。"):
            self.assertTrue(is_simile_sentence(sentence), sentence)
        for sentence in ("他一如既往地沉默。", "一如往日，他早早起身。",
                         "他的忠诚始终如一。", "十年如一日地守着。",
                         "他不知如何是好。"):
            self.assertFalse(is_simile_sentence(sentence), sentence)


class StyleAnalyzerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.metrics = StyleAnalyzer().analyze(fx.synthetic_corpus(chapters=6))

    def test_contract_keys_present(self):
        for key in ("text_summary", "sentence_structure", "paragraph_rhythm", "dialogue_features",
                    "punctuation_density", "punctuation_ratios", "rhetoric_features",
                    "perspective_and_narration", "description_density", "imagery_clusters",
                    "style_markers"):
            self.assertIn(key, self.metrics)

    def test_ratios_are_bounded(self):
        sent = self.metrics["sentence_structure"]
        self.assertLessEqual(sent["short_sent_ratio"], 1.0)
        self.assertLessEqual(sent["long_sent_ratio"], 1.0)
        self.assertLessEqual(self.metrics["dialogue_features"]["dialogue_ratio"], 1.0)
        self.assertGreater(sent["avg_sent_len"], 0)

    def test_empty_text_returns_empty_result_shape(self):
        empty = StyleAnalyzer().analyze("")
        self.assertEqual(empty["text_summary"]["total_chars"], 0)
        self.assertEqual(empty["style_markers"], [])


class DialogueAnalyzerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.analyzer = DialogueAnalyzer()
        cls.data = cls.analyzer.extract_dialogues(fx.synthetic_corpus(chapters=20))

    def test_dialogue_ratio_and_tags(self):
        self.assertGreater(self.data["total_quotes"], 0)
        self.assertGreater(self.data["dialogue_ratio"], 0.0)
        self.assertTrue(self.data["tag_frequencies"])

    def test_high_confidence_speakers_require_recurrence_across_chapters(self):
        for speaker in self.data["high_confidence_speakers"]:
            self.assertGreaterEqual(speaker["occurrences"], 3)
            self.assertGreaterEqual(speaker["chapters_count"], 2)

    def test_speaker_normalization_strips_glued_verbs(self):
        self.assertEqual(normalize_speaker_name("林砚点头"), "林砚")
        self.assertEqual(normalize_speaker_name("苏疏笑道"), "苏疏")


if __name__ == "__main__":
    unittest.main()
