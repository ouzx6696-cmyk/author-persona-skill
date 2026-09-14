# -*- coding: utf-8 -*-
"""End-to-end pipeline contract: prepare -> (LLM) -> finalize -> artifacts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from author_persona_skill import finalize_analysis
from author_persona_skill.contracts import PREPARE_SCHEMA_VERSION

from tests import _fixtures as fx


class PrepareContractTest(unittest.TestCase):
    """prepare_analysis must publish a self-describing stage contract."""

    def test_returns_declared_keys_and_schema_version(self):
        prep = fx.prepared()
        for key in (
            "llm_prompt", "llm_system_msg", "evidence_store", "evidence_store_ids",
            "era_map", "era_id_map", "era_spans", "quantitative_features",
            "metric_registry", "placeholder_map", "proper_noun_candidates", "prepare_meta",
        ):
            self.assertIn(key, prep)
        self.assertEqual(prep["prepare_meta"]["prepare_schema_version"], PREPARE_SCHEMA_VERSION)

    def test_prompt_carries_evidence_ids_and_placeholder_registry(self):
        prep = fx.prepared()
        prompt = prep["llm_prompt"]
        first_eid = next(iter(prep["evidence_store_ids"]))
        self.assertIn(first_eid, prompt)
        self.assertIn("{{avg_sent_len}}", prompt)
        self.assertIn("UNTRUSTED", prompt)

    def test_rejects_empty_corpus(self):
        from author_persona_skill import prepare_analysis

        with self.assertRaises(ValueError):
            prepare_analysis(corpus_text="   \n\n  ")


class FinalizeHappyPathTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()
        cls.response = fx.valid_response(cls.prep)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.result = finalize_analysis(
            prepare_result=cls.prep,
            llm_response=cls.response,
            output_dir=cls.tmp.name,
            base_name="测试报告",
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_status_passed(self):
        self.assertEqual(self.result["status"], "passed", self.result["validation"]["errors"])
        self.assertEqual(self.result["validation"]["status"], "passed")

    def test_writes_expected_artifacts(self):
        saved = self.result["files_saved"]
        for key in ("report_md_path", "report_json_path", "desensitization_map_path", "manifest_path"):
            path = saved.get(key)
            self.assertTrue(path and Path(path).is_file(), f"{key} missing")
        self.assertIsNone(saved.get("private_evidence_path"))

    def test_report_is_single_source_rendered(self):
        md = Path(self.result["report_path"]).read_text(encoding="utf-8")
        # Parts 0/2/3 come from JSON, not from the LLM prose.
        self.assertIn("〇.1 定位", md)
        self.assertIn("### T01：跨期比喻点染收束", md)
        self.assertIn("### 3.1 注意力顺序", md)
        # Part 1 stays LLM prose with measured values substituted in.
        self.assertIn("### 1.2 小节标题", md)
        self.assertNotIn("{{avg_sent_len}}", md)

    def test_sidecar_schema_and_policy(self):
        data = json.loads(Path(self.result["report_json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "5")
        self.assertEqual(data["artifact_policy"], "public_sanitized")
        self.assertEqual(len(data["technique_cards"]), 3)
        self.assertTrue(data["validation_summary"]["publishable"] in {"passed", "failed"})
        self.assertIn("metric_registry", data["provenance"])

    def test_public_sidecar_hides_corpus_text_and_speakers(self):
        data = json.loads(Path(self.result["report_json_path"]).read_text(encoding="utf-8"))
        blob = json.dumps(data, ensure_ascii=False)
        for quote in self.prep["evidence_store"].values():
            self.assertNotIn(quote[:20], blob)
        for speaker in self.prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]:
            self.assertNotIn(speaker["name"], blob)

    def test_rejected_path_is_none(self):
        self.assertIsNone(self.result["rejected_path"])


class FinalizeRejectionTest(unittest.TestCase):
    """A failing response must never produce official artifacts."""

    def _finalize(self, response: str, **kwargs):
        prep = fx.prepared()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return finalize_analysis(
            prepare_result=prep, llm_response=response, output_dir=tmp.name,
            base_name="被拒报告", **kwargs,
        )

    def test_missing_part_heading_is_rejected(self):
        result = self._finalize(fx.drop_heading(fx.valid_response(fx.prepared()), "第二部分"))
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["report_path"])
        self.assertTrue(Path(result["rejected_path"]).is_file())
        self.assertTrue(any("第二部分" in e for e in result["validation"]["errors"]))

    def test_missing_section_is_rejected(self):
        response = fx.valid_response(fx.prepared()).replace("### 1.7 小节标题", "1.7 小节标题（非标题行）")
        result = self._finalize(response)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("1.7" in e for e in result["validation"]["errors"]))

    def test_unknown_json_root_key_is_rejected(self):
        response = fx.mutate_json(fx.valid_response(fx.prepared()),
                                 lambda d: d.update({"extra_field": "x"}))
        result = self._finalize(response)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("非法字段" in e for e in result["validation"]["errors"]))

    def test_unresolvable_placeholder_is_rejected(self):
        response = fx.valid_response(fx.prepared()).replace("{{avg_sent_len}}", "{{no_such_metric}}")
        result = self._finalize(response)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("占位符" in e for e in result["validation"]["errors"]))

    def test_repair_brief_is_attached_on_rejection(self):
        result = self._finalize(fx.drop_heading(fx.valid_response(fx.prepared()), "第三部分"))
        brief = result["validation"].get("repair_brief")
        self.assertIsNotNone(brief, "rejected runs must carry an actionable repair brief")
        self.assertTrue(brief["blocking_errors"])
        self.assertTrue(brief["instructions"])
        self.assertIn("repair_prompt", result)


class FidelityLoopTest(unittest.TestCase):

    def _run(self, trial):
        prep = fx.prepared()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return finalize_analysis(
            prepare_result=prep,
            llm_response=fx.valid_response(prep),
            output_dir=tmp.name,
            base_name="保真报告",
            trial_text=trial,
        )

    def test_trial_text_appends_appendix_and_reports_verdict(self):
        result = self._run(fx.trial_text())
        self.assertIsNotNone(result["fidelity"])
        md = Path(result["report_path"]).read_text(encoding="utf-8")
        self.assertIn("附录：保真闭环校验", md)
        # The report is written either way; the top-level status mirrors the
        # fidelity verdict, which is an independent self-check.
        expected = "passed" if result["fidelity"]["status"] == "passed" else "failed"
        self.assertEqual(result["status"], expected)

    def test_undersized_scene_fails_fidelity_but_keeps_report(self):
        result = self._run("日常\n太短了。")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["fidelity"]["status"], "failed")
        # Report itself was still rendered (fidelity is an independent self-check).
        self.assertTrue(Path(result["report_path"]).is_file())
        self.assertTrue(any("800" in issue for issue in result["fidelity"]["scene_requirements"]["issues"]))

    def test_dynamic_bands_are_wired_from_prepare(self):
        prep = fx.prepared()
        result = finalize_analysis(
            prepare_result=prep,
            llm_response=fx.valid_response(prep),
            trial_text=fx.trial_text(),
        )
        self.assertTrue(result["fidelity"]["dynamic_bands"], "per-era windows must feed MAD bands")


class SystemPromptTest(unittest.TestCase):

    def test_system_prompt_generated_with_quantified_bans(self):
        prep = fx.prepared(options={"generate_system_prompt": True})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        result = finalize_analysis(
            prepare_result=prep,
            llm_response=fx.valid_response(prep),
            output_dir=tmp.name,
            base_name="分身报告",
        )
        self.assertEqual(result["status"], "passed", result["validation"]["errors"])
        prompt = result["system_prompt"]
        self.assertIsNotNone(prompt)
        self.assertIn("量化禁令", prompt)
        self.assertIn("作家分身系统提示词", prompt)
        self.assertTrue(Path(result["files_saved"]["system_prompt_path"]).is_file())

    def test_sanitized_mode_never_names_the_author(self):
        prep = fx.prepared(key="sys-prompt", options={"generate_system_prompt": True})
        result = finalize_analysis(prepare_result=prep, llm_response=fx.valid_response(prep))
        self.assertNotIn("测试作者", result["system_prompt"])
        self.assertNotIn("测试书", result["system_prompt"])


if __name__ == "__main__":
    unittest.main()
