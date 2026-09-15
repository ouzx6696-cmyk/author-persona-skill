# -*- coding: utf-8 -*-
"""分身配套产物：六场景强化、部署配置、三套风格模板。

三项都曾在 v7.0.0 存在、在迭代中丢失。这里的断言锚定各自的可测行为，防止再次
静默消失。
"""
from __future__ import annotations

import json
import unittest

from author_persona_skill.persona.deployment import build_deployment_config
from author_persona_skill.persona.scene_templates import (
    SCENE_TYPES,
    add_scene_enhancement,
    build_scene_enhancement,
)
from author_persona_skill.persona.style_templates import (
    STYLE_TEMPLATE_NAMES,
    render_all_style_templates,
)
from author_persona_skill.report.renderer import extract_json_block, render_report_outputs

from tests import _fixtures as fx


def _report_json(key: str = "w3") -> dict:
    prep = fx.prepared(key=key)
    prose, data = extract_json_block(fx.valid_response(prep))
    rendered = render_report_outputs(
        prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="配套")
    return rendered["report_json"], prep


class SceneTemplateTest(unittest.TestCase):

    def test_all_six_scenes_render(self):
        quant = fx.prepared(key="w3")["quantitative_features"]
        for scene in SCENE_TYPES:
            with self.subTest(scene=scene):
                block = build_scene_enhancement(scene, quant)
                self.assertIn("场景强化指令", block)
                self.assertGreater(len(block), 100)

    def test_scene_block_is_labeled_as_generation_guidance(self):
        # 生成侧指令必须显式标注，避免与「报告数值只能来自占位符」混淆。
        quant = fx.prepared(key="w3")["quantitative_features"]
        block = build_scene_enhancement("battle", quant)
        self.assertIn("生成指导", block)

    def test_thresholds_are_relative_to_measured_baseline(self):
        quant = fx.prepared(key="w3")["quantitative_features"]
        avg = quant["sentence_structure"]["avg_sent_len"]
        block = build_scene_enhancement("scene", quant)
        # 不超过平均句长×1.5 -> 绝对上限以四舍五入的整数出现
        self.assertIn(str(round(avg * 1.5)), block)
        self.assertIn("平均句长×1.5", block)

    def test_unknown_scene_yields_empty(self):
        self.assertEqual(build_scene_enhancement("nope", {}), "")

    def test_add_scene_enhancement_is_noop_when_unset(self):
        prompt = "基线提示词"
        self.assertEqual(add_scene_enhancement(prompt, None, {}), prompt)
        self.assertEqual(add_scene_enhancement(prompt, "", {}), prompt)
        self.assertEqual(add_scene_enhancement(prompt, "invalid", {}), prompt)

    def test_add_scene_enhancement_appends_block(self):
        quant = fx.prepared(key="w3")["quantitative_features"]
        out = add_scene_enhancement("基线提示词", "emotion", quant)
        self.assertTrue(out.startswith("基线提示词"))
        self.assertIn("情感场景", out)


class DeploymentConfigTest(unittest.TestCase):

    def test_temperature_formula_matches_archive(self):
        # short_rate=34 (%) -> 0.85 + min(0.10, 9*0.004)=0.85+0.036=0.886 -> 0.89
        quant = {"sentence_structure": {"short_sent_ratio_pct": "34.0%"}}
        cfg = build_deployment_config(quant)
        self.assertEqual(cfg["platforms"]["dify"]["temperature"], 0.89)

    def test_mid_band_short_rate(self):
        # 20% -> 0.75 + 5*0.01 = 0.80
        cfg = build_deployment_config({"sentence_structure": {"short_sent_ratio_pct": "20%"}})
        self.assertEqual(cfg["platforms"]["claude"]["temperature"], 0.8)

    def test_low_band_short_rate(self):
        # 10% -> 0.70 + 0.05 = 0.75
        cfg = build_deployment_config({"sentence_structure": {"short_sent_ratio_pct": "10%"}})
        self.assertEqual(cfg["platforms"]["claude"]["temperature"], 0.75)

    def test_temperature_is_clamped(self):
        cfg = build_deployment_config({"sentence_structure": {"short_sent_ratio_pct": "100%"}})
        for platform in cfg["platforms"].values():
            self.assertLessEqual(platform["temperature"], 0.95)
            self.assertGreaterEqual(platform["temperature"], 0.65)

    def test_exclamation_bump(self):
        base = build_deployment_config({"sentence_structure": {"short_sent_ratio_pct": "20%"}})
        bumped = build_deployment_config({
            "sentence_structure": {"short_sent_ratio_pct": "20%"},
            "punctuation_density": {"exclamation": 9.0},
        })
        self.assertAlmostEqual(
            bumped["platforms"]["dify"]["temperature"],
            base["platforms"]["dify"]["temperature"] + 0.05, places=2)

    def test_max_tokens_dialogue_tiers(self):
        heavy = build_deployment_config({
            "sentence_structure": {"short_sent_ratio_pct": "20%"},
            "dialogue_features": {"dialogue_ratio": 0.6, "total_quotes": 3500},
        })
        self.assertEqual(heavy["platforms"]["dify"]["max_tokens"], 8192)

    def test_all_platforms_present(self):
        cfg = build_deployment_config({})
        self.assertEqual(
            set(cfg["platforms"]),
            {"dify", "coze", "solo", "chatgpt", "claude"})


class StyleTemplateTest(unittest.TestCase):

    def test_three_templates_render(self):
        report_json, _ = _report_json("w3")
        templates = render_all_style_templates(report_json)
        self.assertEqual(set(templates), set(STYLE_TEMPLATE_NAMES))
        self.assertEqual(set(templates), {"identification", "transfer", "dialogue_generation"})

    def test_identification_requires_suggestions_below_six(self):
        report_json, _ = _report_json("w3")
        text = render_all_style_templates(report_json)["identification"]
        self.assertIn("1–10", text)
        self.assertIn("至少 3 条", text)

    def test_transfer_has_six_rules_and_measured_targets(self):
        report_json, _ = _report_json("w3")
        text = render_all_style_templates(report_json)["transfer"]
        self.assertIn("每 300 字内至少出现 1 次对话或动作", text)
        self.assertIn("对照数据", text)

    def test_dialogue_generation_carries_measured_voices(self):
        report_json, _ = _report_json("w3")
        text = render_all_style_templates(report_json)["dialogue_generation"]
        self.assertIn("口吻类型", text)
        self.assertIn("口头禅", text)

    def test_templates_never_carry_real_names(self):
        report_json, prep = _report_json("w3")
        blob = json.dumps(render_all_style_templates(report_json), ensure_ascii=False)
        for name in ("测试作者", "测试书"):
            self.assertNotIn(name, blob)
        for speaker in prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]:
            self.assertNotIn(speaker["name"], blob)


class ReportJsonArtifactsTest(unittest.TestCase):

    def test_report_json_carries_new_blocks(self):
        report_json, _ = _report_json("w3")
        self.assertIn("deployment_config", report_json)
        self.assertIn("style_templates", report_json)
        self.assertEqual(
            set(report_json["style_templates"]), set(STYLE_TEMPLATE_NAMES))

    def test_report_json_has_no_identity(self):
        report_json, _ = _report_json("w3")
        blob = json.dumps(report_json, ensure_ascii=False)
        for name in ("测试作者", "测试书"):
            self.assertNotIn(name, blob)

    def test_appendix_b_renders_quant_extension(self):
        _, prep = _report_json("w3")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="配套")
        md = rendered["full_markdown"]
        self.assertIn("附录 B：定量扩展", md)
        self.assertIn("可读性分级", md)
        self.assertIn("风格 DNA 候选（降序，非权威）", md)
        for sub in ("### B.1", "### B.2", "### B.3", "### B.4", "### B.5", "### B.6"):
            self.assertIn(sub, md, sub)

    def test_appendix_b4_present_even_without_hits(self):
        """未命中也要出 B.4：「整节缺席」会被读成「没测」，而实际含义是「未达门槛」。"""
        _, prep = _report_json("w3")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="配套")
        md = rendered["full_markdown"]
        section = md[md.find("### B.4"):md.find("### B.5")]
        self.assertIn("特色系统关键词命中", section)

    def test_appendix_b5_reads_nested_dialogue_functions(self):
        """dialogue_functions 是嵌套结构：读顶层键会把全部数值渲染成「—」。"""
        _, prep = _report_json("w3")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="配套")
        md = rendered["full_markdown"]
        section = md[md.find("### B.5"):md.find("### B.6")]
        dist = (prep["quantitative_features"]["dialogue_features"]
                .get("dialogue_functions", {}).get("distribution", {}))
        self.assertTrue(dist, "fixture 应带对话功能分布")
        for label, value in dist.items():
            if value:
                self.assertIn(f"| 对话功能·{label} | {value}", section)
        # POV 是 dict，必须取字段而非打印整个 dict
        self.assertNotIn("{'", section)
        self.assertIn("主导视角", section)

    def test_appendix_c_renders_persona_kit(self):
        _, prep = _report_json("w3")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="配套")
        md = rendered["full_markdown"]
        self.assertIn("附录 C：分身配套产物", md)
        self.assertIn("dify", md)
        self.assertIn("identification", md)

    def test_appendices_carry_no_identity(self):
        """附录只读公开侧数据，仍不得带出作者名/作品名/角色名。"""
        _, prep = _report_json("w3")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="配套")
        md = rendered["full_markdown"]
        for name in ("测试作者", "测试书"):
            self.assertNotIn(name, md)
        speakers = (prep["quantitative_features"].get("dialogue_features") or {}).get(
            "high_confidence_speakers") or []
        for speaker in speakers:
            if speaker.get("name"):
                self.assertNotIn(speaker["name"], md)

    def test_appendices_do_not_disturb_four_layer_headings(self):
        _, prep = _report_json("w3")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="配套")
        md = rendered["full_markdown"]
        for heading in ("## 第〇部分", "## 第一部分", "## 第二部分", "## 第三部分"):
            self.assertIn(heading, md)
        # 附录一律排在四层正文之后
        self.assertGreater(md.find("## 附录 A"), md.find("## 第三部分"))


class SceneTypeFinalizeTest(unittest.TestCase):
    """scene_type 是 finalize 的可选入参：缺省不改变行为，给出时追加场景块。"""

    def _finalize(self, **kwargs):
        prep = fx.prepared(key="scene-finalize")
        response = fx.valid_response(prep)
        from author_persona_skill.pipeline import finalize_analysis
        return finalize_analysis(
            prepare_result=prep, llm_response=response, **kwargs)

    def test_default_unchanged(self):
        result = self._finalize()
        self.assertEqual(result["status"], "passed", result["validation"].get("errors"))
        self.assertIsNone(result["system_prompt"])

    def test_scene_type_appends_to_persona_prompt(self):
        prep = fx.prepared(key="scene-finalize", options={"generate_system_prompt": True})
        response = fx.valid_response(prep)
        from author_persona_skill.pipeline import finalize_analysis
        result = finalize_analysis(
            prepare_result=prep, llm_response=response, scene_type="battle")
        self.assertEqual(result["status"], "passed", result["validation"].get("errors"))
        self.assertIsNotNone(result["system_prompt"])
        self.assertIn("战斗场景", result["system_prompt"])

    def test_invalid_scene_type_is_ignored(self):
        prep = fx.prepared(key="scene-finalize", options={"generate_system_prompt": True})
        response = fx.valid_response(prep)
        from author_persona_skill.pipeline import finalize_analysis
        result = finalize_analysis(
            prepare_result=prep, llm_response=response, scene_type="not-a-scene")
        self.assertEqual(result["status"], "passed")
        self.assertNotIn("场景强化指令", result["system_prompt"] or "")


if __name__ == "__main__":
    unittest.main()
