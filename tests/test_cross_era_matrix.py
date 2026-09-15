# -*- coding: utf-8 -*-
"""跨期对比矩阵与趋势、语义子维度、正反例抽取。"""
from __future__ import annotations

import json
import unittest

from author_persona_skill.analyzers.cross_era import (
    MATRIX_DIMENSIONS,
    build_cross_era_matrix,
    build_semantic_dimensions,
    classify_trend,
    extract_exemplars,
    measure_dialogue_functions,
    measure_pov_stability,
)

from tests import _fixtures as fx


class TrendClassificationTest(unittest.TestCase):

    def test_rising(self):
        self.assertEqual(classify_trend([1.0, 2.0, 3.0, 4.0]), "上升")

    def test_falling(self):
        self.assertEqual(classify_trend([4.0, 3.0, 2.0, 1.0]), "下降")

    def test_stable(self):
        self.assertEqual(classify_trend([10.0, 10.2, 9.9, 10.1]), "稳定")

    def test_oscillating_is_volatile(self):
        self.assertEqual(classify_trend([1.0, 9.0, 1.0, 9.0]), "波动")

    def test_single_point_is_insufficient(self):
        self.assertEqual(classify_trend([5.0]), "数据不足")

    def test_empty_is_insufficient(self):
        self.assertEqual(classify_trend([]), "数据不足")

    def test_all_zero_is_stable(self):
        self.assertEqual(classify_trend([0.0, 0.0, 0.0]), "稳定")


class CrossEraMatrixTest(unittest.TestCase):

    def test_six_dimensions_defined(self):
        self.assertEqual(len(MATRIX_DIMENSIONS), 6)
        names = [d[0] for d in MATRIX_DIMENSIONS]
        for name in ("平均句长", "短句率", "长句率", "平均段长", "对话占比", "词汇丰富度"):
            self.assertIn(name, names)

    def test_matrix_from_real_windows(self):
        prep = fx.prepared(key="w6")
        matrix = prep["cross_era_matrix"]
        self.assertGreaterEqual(len(matrix["eras"]), 2)
        self.assertEqual(len(matrix["dimensions"]), 6)
        for dim in matrix["dimensions"]:
            self.assertEqual(len(dim["values"]), len(matrix["eras"]))
            self.assertIn(dim["trend"],
                          {"上升", "下降", "波动", "稳定", "数据不足"})

    def test_empty_windows_shaped(self):
        matrix = build_cross_era_matrix([])
        self.assertEqual(matrix["eras"], [])
        self.assertEqual(matrix["dimensions"], [])

    def test_deterministic(self):
        prep = fx.prepared(key="w6")
        windows = prep["era_window_metrics"]
        self.assertEqual(build_cross_era_matrix(windows), build_cross_era_matrix(windows))

    def test_parses_pct_strings(self):
        matrix = build_cross_era_matrix([
            {"era": "A", "sentence_structure": {"short_sent_ratio_pct": "30.0%",
                                                "avg_sent_len": 20}},
            {"era": "B", "sentence_structure": {"short_sent_ratio_pct": "45.0%",
                                                "avg_sent_len": 10}},
        ])
        dims = {d["dimension"]: d for d in matrix["dimensions"]}
        self.assertEqual(dims["短句率"]["values"], [30.0, 45.0])
        self.assertEqual(dims["短句率"]["trend"], "上升")


class DialogueFunctionTest(unittest.TestCase):

    def test_four_categories(self):
        result = measure_dialogue_functions(["为何如此？", "住手！", "我爱你", "走吧"])
        self.assertEqual(set(result["counts"]),
                         {"信息交换", "冲突对抗", "情感表达", "日常闲聊"})

    def test_distribution_sums_to_one(self):
        result = measure_dialogue_functions(["为何？", "住手！", "走吧"])
        self.assertAlmostEqual(sum(result["distribution"].values()), 1.0, places=3)

    def test_empty_is_shaped(self):
        result = measure_dialogue_functions([])
        self.assertEqual(result["total_quotes"], 0)

    def test_method_labelled(self):
        self.assertEqual(measure_dialogue_functions(["x"])["method"], "keyword-heuristic")

    def test_wired_into_dialogue_features(self):
        prep = fx.prepared(key="w6")
        functions = prep["quantitative_features"]["dialogue_features"]["dialogue_functions"]
        self.assertIn("distribution", functions)
        self.assertGreater(functions["total_quotes"], 0)


class PovStabilityTest(unittest.TestCase):

    def test_third_person_dominant(self):
        text = "他走了。她笑了。他们看着他，他也看着他们。"
        result = measure_pov_stability(text)
        self.assertEqual(result["dominant_pov"], "第三人称主导")

    def test_first_person_dominant(self):
        text = "我走了。我看着咱的路。我俺都记得。" * 3
        self.assertEqual(measure_pov_stability(text)["dominant_pov"], "第一人称主导")

    def test_empty_is_no_data(self):
        self.assertEqual(measure_pov_stability("")["dominant_pov"], "无数据")

    def test_stability_field_present(self):
        self.assertIn(measure_pov_stability("他说。她说。")["stability"], {"稳定", "波动"})


class SemanticDimensionsTest(unittest.TestCase):

    def test_aggregate_shape(self):
        result = build_semantic_dimensions("他说。", ["为何？"])
        self.assertIn("dialogue_functions", result)
        self.assertIn("pov_stability", result)

    def test_in_analyzer_output(self):
        prep = fx.prepared(key="w6")
        q = prep["quantitative_features"]
        sem = q["semantic_dimensions"]
        self.assertIn("pov_stability", sem)
        # 语义层必须复现 dialogue_features 的实测分布，不得因未传引语而恒为零。
        self.assertEqual(sem["dialogue_functions"], q["dialogue_features"]["dialogue_functions"])
        self.assertGreater(sem["dialogue_functions"]["total_quotes"], 0)

    def test_explicit_distribution_is_reused_verbatim(self):
        injected = {"counts": {"信息交换": 3}, "distribution": {"信息交换": 1.0},
                    "total_quotes": 3, "method": "keyword-heuristic"}
        result = build_semantic_dimensions("他说。", dialogue_functions=injected)
        self.assertIs(result["dialogue_functions"], injected)


class ExemplarTest(unittest.TestCase):

    def test_positive_and_negative_buckets(self):
        result = extract_exemplars([
            {"chunk_id": "c1", "text": "他握紧了铜铃，一步踏出。"},
            {"chunk_id": "c2", "text": "他低声道，沉声道，冷笑道……幽幽地……"},
        ])
        self.assertIn("exemplars_positive", result)
        self.assertIn("exemplars_negative", result)
        self.assertTrue(result["exemplars_negative"])

    def test_capped(self):
        many = [{"chunk_id": f"c{i}", "text": "他握紧了铜铃，一步踏出。"} for i in range(20)]
        self.assertLessEqual(len(extract_exemplars(many, max_items=3)["exemplars_positive"]), 3)

    def test_not_in_public_json(self):
        # 正反例是原文片段，只允许进私有通道。
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        import tempfile
        from pathlib import Path
        prep = fx.prepared(key="w6")
        prose, data = extract_json_block(fx.valid_response(prep))
        with tempfile.TemporaryDirectory() as tmp:
            rendered = render_report_outputs(
                prose_markdown=prose, parsed_json=data, prepare_result=prep,
                output_dir=Path(tmp), base_name="ex")
            blob = json.dumps(rendered["report_json"], ensure_ascii=False)
            self.assertNotIn("exemplars_positive", blob)
            self.assertNotIn("exemplars_negative", blob)


class AppendixTest(unittest.TestCase):

    def test_appendix_a_rendered_in_markdown(self):
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        prep = fx.prepared(key="w6")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="附录")
        self.assertIn("附录 A：跨期对比矩阵", rendered["full_markdown"])

    def test_appendix_does_not_disturb_four_layer_headings(self):
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        prep = fx.prepared(key="w6")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="附录")
        for heading in ("## 第〇部分", "## 第一部分", "## 第二部分", "## 第三部分"):
            self.assertIn(heading, rendered["full_markdown"])

    def test_report_json_carries_matrix(self):
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        prep = fx.prepared(key="w6")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="附录")
        self.assertIn("cross_era_matrix", rendered["report_json"])

    def test_matrix_has_no_identity(self):
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        prep = fx.prepared(key="w6")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="附录")
        blob = json.dumps(rendered["report_json"], ensure_ascii=False)
        for name in ("测试作者", "测试书"):
            self.assertNotIn(name, blob)


if __name__ == "__main__":
    unittest.main()
