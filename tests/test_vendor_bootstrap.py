# -*- coding: utf-8 -*-
"""内嵌分词依赖的引导与降级。

v7.0.0 的 `libs/` 在 v10 迭代中被删掉，低层测量（命名实体/词性/世界观五类）随之
静默归零。这一组用例把「依赖可见、引导幂等、缺失可降级」三件事钉死，防止依赖再
次无声消失或变成一个必装项。
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

from author_persona_skill import _vendor  # noqa: E402
from author_persona_skill.analyzers import tokenizer as tk  # noqa: E402


class LibsLayoutTest(unittest.TestCase):

    def test_libs_directory_ships_with_skill(self):
        libs = ROOT / "libs"
        self.assertTrue((libs / "jieba" / "__init__.py").is_file())
        self.assertTrue((libs / "jieba" / "dict.txt").is_file())

    def test_finds_libs_root_not_package_dir(self):
        """探测点必须是 sys.path 根（含 jieba/__init__.py），不能是包目录本身。"""
        found = _vendor.find_libs_path()
        self.assertIsNotNone(found, "未找到内嵌依赖目录")
        self.assertTrue((Path(found) / "jieba" / "__init__.py").is_file())

    def test_candidates_include_skill_root_libs(self):
        candidates = [str(p).replace("\\", "/") for p in _vendor.libs_candidates()]
        self.assertIn(str(ROOT / "libs").replace("\\", "/"), candidates)

    def test_available_flag_is_true(self):
        self.assertTrue(_vendor.vendored_libs_available())


class BootstrapIdempotencyTest(unittest.TestCase):

    def test_ensure_is_idempotent(self):
        first = _vendor.ensure_libs_on_path()
        path_len_after_first = len(sys.path)
        second = _vendor.ensure_libs_on_path()
        self.assertEqual(first, second)
        self.assertEqual(path_len_after_first, len(sys.path), "重复调用不得重复插入 sys.path")

    def test_ensure_returns_usable_path(self):
        path = _vendor.ensure_libs_on_path()
        self.assertTrue(path)
        self.assertTrue((Path(path) / "jieba" / "__init__.py").is_file())

    def test_tokenizer_resolves_vendored_copy_not_site_packages(self):
        """污染场景：即使 sys.path 里有别的 jieba，也必须先命中内嵌副本。"""
        self.assertTrue(tk.tokenizer_available())
        info = tk.tokenizer_status()
        self.assertIn("vendored", str(info.get("tokenizer", "")))
        self.assertNotIn("site-packages", str(tk._jieba_mod.__file__ or "").replace("\\", "/"))

    def test_vendored_path_precedes_site_packages(self):
        """内嵌目录必须排在 site-packages 之前，装了别的 jieba 也先命中内嵌版。

        断言不用 ``sys.path[0]``：pytest 自己会在包导入后往头部插 rootdir，
        位置会被改动。真正承重的契约是「先于任何 site-packages 条目」。
        """
        libs = _vendor.ensure_libs_on_path()
        self.assertIn(libs, sys.path)
        libs_index = sys.path.index(libs)
        site_indexes = [
            i for i, entry in enumerate(sys.path)
            if "site-packages" in entry or "dist-packages" in entry
        ]
        if site_indexes:
            self.assertLess(libs_index, min(site_indexes))
        self.assertTrue((Path(libs) / "jieba" / "__init__.py").is_file())

    def test_bootstrap_runs_before_package_api(self):
        """包 __init__ 内必须先引导依赖，再 import 分析器。"""
        import author_persona_skill
        self.assertTrue(author_persona_skill.__file__)
        self.assertTrue(_vendor._probed, "包导入后应已完成探测")


class ColdStartTest(unittest.TestCase):
    """冷启动：在没有预置 sys.path 的新进程里直接 import 包也能拿到分词器。"""

    def test_fresh_interpreter_sees_tokenizer(self):
        code = (
            "import sys; sys.path.insert(0, r'{scripts}');"
            "from author_persona_skill.analyzers import tokenizer as tk;"
            "print('OK' if tk.tokenizer_available() else 'MISSING')"
        ).format(scripts=str(SCRIPTS))
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertIn("OK", proc.stdout)

    def test_fresh_interpreter_posseg_works(self):
        code = (
            "import sys; sys.path.insert(0, r'{scripts}');"
            "from author_persona_skill.analyzers import low_level;"
            "r = low_level.analyze_low_level('他站在崖边。风很大，吹得衣袍猎猎作响。');"
            "print(r['tokenizer']['pos_available'], r['tokenizer']['available'])"
        ).format(scripts=str(SCRIPTS))
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertIn("True True", proc.stdout)


class DegradationTest(unittest.TestCase):
    """缺 jieba 时全套指标仍可算，并标注 degraded（不得抛异常）。"""

    def setUp(self):
        self._saved = (tk._jieba_mod, tk._posseg_mod, tk._load_attempted, tk._load_error)

    def tearDown(self):
        (tk._jieba_mod, tk._posseg_mod, tk._load_attempted, tk._load_error) = self._saved

    def test_missing_tokenizer_degrades_without_raising(self):
        tk._jieba_mod = None
        tk._posseg_mod = None
        tk._load_attempted = True
        self.assertFalse(tk.tokenizer_available())
        result = tk.cut("他站在崖边，风很大。")
        self.assertIsInstance(result, list)
        self.assertTrue(result)
        pairs = tk.posseg("他站在崖边。")
        self.assertIsInstance(pairs, list)
        for pair in pairs:
            self.assertEqual(len(pair), 2)

    def test_low_level_marks_degraded(self):
        from author_persona_skill.analyzers import low_level
        tk._jieba_mod = None
        tk._posseg_mod = None
        tk._load_attempted = True
        result = low_level.analyze_low_level("他站在崖边，风很大，吹得衣袍猎猎作响。")
        self.assertFalse(result["tokenizer"]["available"])
        self.assertTrue(result["readability"]["degraded"])
        self.assertTrue(result["vocabulary_richness"]["degraded"])
        self.assertIn("error", result["tokenizer"])

    def test_flag_lookup_fallback_returns_well_formed_words(self):
        tk._jieba_mod = None
        tk._posseg_mod = None
        tk._load_attempted = True
        words = tk.words_with_flag("苏疏站在崖边。", ("n",))
        self.assertIsInstance(words, list)
        self.assertTrue(all(isinstance(w, str) for w in words))


if __name__ == "__main__":
    unittest.main()
