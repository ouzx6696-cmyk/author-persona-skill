# -*- coding: utf-8 -*-
"""Corpus layer: chapter indexing, era planning, and safe file reading."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from author_persona_skill.corpus.chapter_index import build_chapter_index
from author_persona_skill.corpus.file_processor import read_text_file
from author_persona_skill.corpus.reading_plan import create_reading_plan, era_id_for_label

from tests import _fixtures as fx


class ChapterIndexTest(unittest.TestCase):

    def test_detects_numbered_chapters(self):
        chapters, is_fallback = build_chapter_index(fx.synthetic_corpus(chapters=12))
        self.assertFalse(is_fallback)
        self.assertEqual(len(chapters), 12)
        self.assertEqual(chapters[0]["chapter_idx"], 0)
        self.assertEqual(chapters[0]["chapter_id"], "C0001")
        self.assertEqual(chapters[-1]["end"], len(fx.synthetic_corpus(chapters=12)))

    def test_falls_back_to_virtual_segments(self):
        chapters, is_fallback = build_chapter_index("没有章节标题的一整段文本。" * 400)
        self.assertTrue(is_fallback)
        self.assertGreater(len(chapters), 1)
        self.assertTrue(all(c["title"].startswith("分段_") for c in chapters))


class ReadingPlanTest(unittest.TestCase):

    def test_large_corpus_gets_five_eras_and_stays_within_budget_band(self):
        text = fx.synthetic_corpus(chapters=60)
        chapters, is_fallback = build_chapter_index(text)
        plan = create_reading_plan(text, chapters, budget_chars=8000, is_fallback=is_fallback)
        eras = {c["era"] for c in plan["sampled_chapters"]}
        self.assertEqual(len(eras), 5, eras)
        self.assertLessEqual(len(plan["sampled_chapters"]), len(chapters))
        self.assertLess(plan["coverage_pct"], 100.0)

    def test_small_corpus_is_fully_sampled_but_still_labelled(self):
        text = fx.synthetic_corpus(chapters=4)
        chapters, is_fallback = build_chapter_index(text)
        plan = create_reading_plan(text, chapters, budget_chars=150000, is_fallback=is_fallback)
        self.assertEqual(plan["coverage_pct"], 100.0)
        self.assertTrue(all(c.get("era") for c in plan["sampled_chapters"]))

    def test_era_ids_are_stable_machine_keys(self):
        self.assertEqual(era_id_for_label("开头 (Begin)"), "ERA_1")
        self.assertEqual(era_id_for_label("结尾 (Ending)"), "ERA_5")
        self.assertEqual(era_id_for_label("未分期"), "")

    def test_zero_budget_is_rejected(self):
        text = fx.synthetic_corpus(chapters=30)
        chapters, is_fallback = build_chapter_index(text)
        with self.assertRaises(ValueError):
            create_reading_plan(text, chapters, budget_chars=0, is_fallback=is_fallback)


class FileProcessorTest(unittest.TestCase):

    def _read(self, data: bytes):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "corpus.txt"
        path.write_bytes(data)
        return read_text_file(path)

    def test_utf8_and_bom(self):
        text, enc = self._read("中文正文。".encode("utf-8"))
        self.assertEqual(text, "中文正文。")
        self.assertEqual(enc, "utf-8")
        text, enc = self._read("中文正文。".encode("utf-8-sig"))
        self.assertEqual(text, "中文正文。")
        self.assertEqual(enc, "utf-8-sig")

    def test_gb18030_is_detected(self):
        text, enc = self._read("中文正文，编码测试。".encode("gb18030"))
        self.assertEqual(text, "中文正文，编码测试。")
        self.assertIn(enc, {"gb18030", "gbk"})

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_text_file(Path(tempfile.gettempdir()) / "definitely-missing-corpus.txt")


if __name__ == "__main__":
    unittest.main()
