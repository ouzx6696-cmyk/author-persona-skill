# -*- coding: utf-8 -*-
"""Fidelity closed loop: scene contract, copy risk, deviations, card evaluation."""
from __future__ import annotations

import unittest

from author_persona_skill.fidelity.fidelity_check import (
    check_copy_risk,
    check_trial_scene_requirements,
    compute_metric_deviations,
    derive_dynamic_tolerances,
    evaluate_card_in_text,
    run_fidelity_check,
    scene_type_coverage,
    split_trial_scenes,
)

from tests import _fixtures as fx


class SceneSplittingTest(unittest.TestCase):

    def test_dash_and_equals_and_heading_delimiters(self):
        text = "场景一正文。\n\n---\n\n场景二正文。\n\n===\n\n# 场景3：冲突\n场景三正文。"
        scenes = split_trial_scenes(text)
        self.assertEqual(len(scenes), 3)
        self.assertTrue(scenes[2].startswith("# 场景3：冲突"))

    def test_accepts_list_input(self):
        self.assertEqual(len(split_trial_scenes(["a", "b"])), 2)

    def test_requirements_enforce_two_to_three_scenes_and_length(self):
        issues = check_trial_scene_requirements(["太短。"])
        self.assertTrue(any("2–3" in issue for issue in issues))
        self.assertTrue(any("800" in issue for issue in issues))

    def test_type_coverage_only_when_labelled(self):
        unlabelled = [fx.scene_block(""), fx.scene_block("")]
        self.assertIsNone(scene_type_coverage(unlabelled))
        labelled = [fx.scene_block("日常"), fx.scene_block("冲突")]
        self.assertEqual(scene_type_coverage(labelled), ["抉择"])


class CopyRiskTest(unittest.TestCase):

    def test_identical_text_is_flagged(self):
        reference = fx.synthetic_corpus(chapters=2)
        result = check_copy_risk(reference[:4000], [reference])
        self.assertTrue(result["is_copy_risk"])
        self.assertGreaterEqual(result["longest_match"], 40)

    def test_independent_text_is_clean(self):
        result = check_copy_risk("全新的原创场景文字，与原文没有任何重叠。", [fx.synthetic_corpus(chapters=2)])
        self.assertFalse(result["is_copy_risk"])

    def test_no_reference_skips_gracefully(self):
        result = check_copy_risk("一些试写文本。", [])
        self.assertFalse(result["is_copy_risk"])
        self.assertIn("跳过", result["reason"])


class DeviationTest(unittest.TestCase):

    def test_deviation_table_covers_four_core_metrics(self):
        metrics = {"sentence_structure": {"avg_sent_len": 20.0, "short_sent_ratio": 0.3},
                   "dialogue_features": {"dialogue_ratio": 0.3},
                   "rhetoric_features": {"metaphor_density": 2.0}}
        deviations, passed = compute_metric_deviations(metrics, metrics)
        self.assertEqual(len(deviations), 4)
        self.assertTrue(passed)
        self.assertTrue(all(row["status"] == "passed" for row in deviations))

    def test_large_drift_fails(self):
        reference = {"sentence_structure": {"avg_sent_len": 40.0, "short_sent_ratio": 0.1},
                     "dialogue_features": {"dialogue_ratio": 0.1},
                     "rhetoric_features": {"metaphor_density": 1.0}}
        trial = {"sentence_structure": {"avg_sent_len": 10.0, "short_sent_ratio": 0.9},
                 "dialogue_features": {"dialogue_ratio": 0.9},
                 "rhetoric_features": {"metaphor_density": 9.0}}
        _, passed = compute_metric_deviations(trial, reference)
        self.assertFalse(passed)

    def test_dynamic_bands_need_enough_windows(self):
        self.assertEqual(derive_dynamic_tolerances([{}, {}, {}]), {})
        windows = [{"sentence_structure": {"avg_sent_len": v}} for v in (18, 20, 22, 24, 21)]
        bands = derive_dynamic_tolerances(windows)
        self.assertIn("avg_sent_len", bands)
        self.assertLess(bands["avg_sent_len"]["lo"], bands["avg_sent_len"]["hi"])

    def test_dynamic_band_rescues_any_metric_inside_the_author_window(self):
        """A value inside the author's natural window is not a fidelity failure.

        The band applies to every spec in the table, not just average sentence
        length (the pre-refactor override only covered that one metric).
        """
        windows = [{"sentence_structure": {"avg_sent_len": v}} for v in (18, 20, 22, 24, 21)]
        bands = derive_dynamic_tolerances(windows)
        reference = {"sentence_structure": {"avg_sent_len": 40.0}}
        trial = {"sentence_structure": {"avg_sent_len": 24.0}}

        rows, passed = compute_metric_deviations(trial, reference)
        self.assertFalse(passed, "24 vs 40 is a 40% drift, outside the fixed ±15%")
        rows, passed = compute_metric_deviations(trial, reference, dynamic_bands=bands)
        self.assertTrue(passed)
        self.assertEqual(rows[0]["basis"], "author_band")
        self.assertIn("作者自然波动区间", rows[0]["threshold"])

    def test_value_outside_the_dynamic_band_still_fails(self):
        windows = [{"sentence_structure": {"avg_sent_len": v}} for v in (18, 20, 22, 24, 21)]
        bands = derive_dynamic_tolerances(windows)
        reference = {"sentence_structure": {"avg_sent_len": 40.0}}
        trial = {"sentence_structure": {"avg_sent_len": 30.0}}  # band is [18, 24]

        rows, passed = compute_metric_deviations(trial, reference, dynamic_bands=bands)
        self.assertFalse(passed)
        self.assertEqual(rows[0]["basis"], "fixed_tolerance")
        self.assertNotIn("作者自然波动区间", rows[0]["threshold"])

    def test_rows_expose_machine_keys(self):
        metrics = {"sentence_structure": {"avg_sent_len": 20.0, "short_sent_ratio": 0.3},
                   "dialogue_features": {"dialogue_ratio": 0.3},
                   "rhetoric_features": {"metaphor_density": 2.0}}
        rows, _ = compute_metric_deviations(metrics, metrics)
        self.assertEqual(
            [row["key"] for row in rows],
            ["avg_sent_len", "short_sent_ratio", "dialogue_ratio", "metaphor_density"],
        )


class CardEvaluationTest(unittest.TestCase):

    def test_metaphor_card_is_covered_by_marker(self):
        card = {"id": "T01", "name": "比喻点染", "definition": "用比喻收束段落。", "steps": []}
        result = evaluate_card_in_text(card, "她的手指宛如冰锥。")
        self.assertEqual(result["status"], "covered")

    def test_unknown_card_is_not_applicable(self):
        result = evaluate_card_in_text({"id": "T02", "name": "叙事结构", "definition": "关于主题的把握。"}, "任意文本")
        self.assertEqual(result["status"], "not_applicable")

    def test_dash_overuse_is_deformed(self):
        card = {"id": "T03", "name": "破折号揭底", "definition": "以破折号插入补注。", "steps": []}
        text = "他抬手——" * 400
        self.assertEqual(evaluate_card_in_text(card, text)["status"], "deformed")


class RunFidelityTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()

    def test_full_run_passes_when_trial_matches_baseline(self):
        """Pass path: trial metrics ARE the baseline, scenes satisfy the contract."""
        trial = fx.trial_text()
        from author_persona_skill.analyzers.style_analyzer import StyleAnalyzer

        result = run_fidelity_check(
            trial_text=trial,
            reference_metrics=StyleAnalyzer().analyze(trial),
            technique_cards=[],
        )
        self.assertEqual(result["status"], "passed", result["overall_reasons"])
        self.assertTrue(result["copy_passed"])
        self.assertEqual(result["probe_summary"]["total"], 3)

    def test_book_baseline_detects_drift(self):
        result = run_fidelity_check(
            trial_text=fx.trial_text(),
            reference_metrics=self.prep["quantitative_features"],
            technique_cards=[],
        )
        self.assertFalse(result["metrics_passed"])
        self.assertTrue(any("定量指标" in reason for reason in result["overall_reasons"]))

    def test_short_trial_fails_scene_gate(self):
        result = run_fidelity_check(trial_text="只有一小段。", reference_metrics=self.prep["quantitative_features"])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["scene_requirements"]["issues"])

    def test_era_windows_are_published_for_downstream_bands(self):
        windows = self.prep.get("era_window_metrics")
        self.assertTrue(windows)
        self.assertGreaterEqual(len(windows), 4)
        self.assertIn("sentence_structure", windows[0])


if __name__ == "__main__":
    unittest.main()
