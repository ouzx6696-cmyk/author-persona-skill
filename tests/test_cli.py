# -*- coding: utf-8 -*-
"""CLI surface: subcommand exit codes and artifact paths."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from author_persona_skill.cli import main

from tests import _fixtures as fx


class CliTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.corpus = self.dir / "corpus.txt"
        self.corpus.write_text(fx.synthetic_corpus(chapters=20), encoding="utf-8")

    def _run(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
            code = main(argv)
        return code, stdout.getvalue()

    def test_no_command_prints_help(self):
        code, out = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("prepare", out)

    def test_analyze_json(self):
        code, out = self._run(["analyze", str(self.corpus), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("sentence_structure", payload)

    def test_plan(self):
        code, out = self._run(["plan", str(self.corpus), "--budget", "20000"])
        self.assertEqual(code, 0)
        self.assertIn("章节索引", out)

    def test_prepare_then_finalize_round_trip(self):
        prep_json = self.dir / "prep.json"
        prompt_file = self.dir / "prompt.txt"
        code, out = self._run([
            "prepare", str(self.corpus), "--author", "测试作者", "--title", "测试书",
            "--budget", "30000", "--output-json", str(prep_json), "--output-prompt", str(prompt_file),
        ])
        self.assertEqual(code, 0, out)
        self.assertTrue(prompt_file.is_file())
        self.assertIn("SYSTEM:", prompt_file.read_text(encoding="utf-8"))

        prep = json.loads(prep_json.read_text(encoding="utf-8"))
        response = self.dir / "response.txt"
        response.write_text(fx.valid_response(prep), encoding="utf-8")
        out_dir = self.dir / "out"
        code, out = self._run([
            "finalize", "--prepare-json", str(prep_json), "--response-file", str(response),
            "--output-dir", str(out_dir), "--base-name", "CLI报告",
        ])
        self.assertEqual(code, 0, out)
        self.assertTrue((out_dir / "CLI报告.md").is_file())
        self.assertTrue((out_dir / "CLI报告.json").is_file())

    def test_finalize_rejection_exits_one_and_writes_rejected(self):
        prep_json = self.dir / "prep.json"
        self._run(["prepare", str(self.corpus), "--budget", "30000", "--output-json", str(prep_json)])
        prep = json.loads(prep_json.read_text(encoding="utf-8"))
        broken = fx.drop_heading(fx.valid_response(prep), "第一部分")
        response = self.dir / "response.txt"
        response.write_text(broken, encoding="utf-8")
        out_dir = self.dir / "out"
        code, out = self._run([
            "finalize", "--prepare-json", str(prep_json), "--response-file", str(response),
            "--output-dir", str(out_dir), "--base-name", "拒绝报告",
        ])
        self.assertEqual(code, 1)
        self.assertIn("已拒绝", out)
        self.assertTrue((out_dir / "拒绝报告_rejected.md").is_file())

    def test_finalize_emits_repair_prompt_file(self):
        prep_json = self.dir / "prep.json"
        self._run(["prepare", str(self.corpus), "--budget", "30000", "--output-json", str(prep_json)])
        prep = json.loads(prep_json.read_text(encoding="utf-8"))
        response = self.dir / "response.txt"
        response.write_text(fx.drop_heading(fx.valid_response(prep), "第二部分"), encoding="utf-8")
        repair_file = self.dir / "repair.txt"
        code, _ = self._run([
            "finalize", "--prepare-json", str(prep_json), "--response-file", str(response),
            "--output-dir", str(self.dir / "out"), "--repair-prompt-out", str(repair_file),
        ])
        self.assertEqual(code, 1)
        self.assertTrue(repair_file.is_file())
        self.assertIn("修复", repair_file.read_text(encoding="utf-8"))

    def test_fidelity_subcommand(self):
        prep_json = self.dir / "prep.json"
        self._run(["prepare", str(self.corpus), "--budget", "30000", "--output-json", str(prep_json)])
        prep = json.loads(prep_json.read_text(encoding="utf-8"))
        response = self.dir / "response.txt"
        response.write_text(fx.valid_response(prep), encoding="utf-8")
        out_dir = self.dir / "out"
        self._run([
            "finalize", "--prepare-json", str(prep_json), "--response-file", str(response),
            "--output-dir", str(out_dir), "--base-name", "保真CLI",
        ])
        trial = self.dir / "trial.txt"
        trial.write_text(fx.trial_text(), encoding="utf-8")
        code, out = self._run([
            "fidelity", "--trial", str(trial), "--report-json", str(out_dir / "保真CLI.json"),
        ])
        self.assertEqual(code, 0, out)
        self.assertIn("保真度闭环校验结果", out)

    def test_missing_corpus_exits_one(self):
        code, out = self._run(["analyze", str(self.dir / "nope.txt")])
        self.assertEqual(code, 1)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
