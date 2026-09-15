# -*- coding: utf-8 -*-
"""Structured report objects: technique cards, thinking layer, writer contract."""
from __future__ import annotations

import unittest

from author_persona_skill.distill.claims import validate_claims
from author_persona_skill.distill.technique_cards import (
    QUOTE_MAX_CHARS,
    TechniqueCard,
    check_card_content_quality,
)
from author_persona_skill.distill.thinking_layer import ThinkingLayer
from author_persona_skill.distill.writer_contract import NOT_PROVIDED, WriterContract

from tests import _fixtures as fx


def _card(**overrides):
    data = {
        "id": "T01",
        "name": "对话尾逗号连写",
        "definition": "引语以逗号收尾，同段内接续一个动作分句再开启下一句引语，使对白与微动作连体。",
        "serves_purpose": "让多轮交锋的对白紧凑连贯",
        "trigger": "两人及以上连续交锋，需要在对话间隙插入微动作时",
        "steps": ["引语收尾用逗号", "动作只留一个分句", "下一句引语紧随其后"],
        "boundary": "独白与跨场景转场时禁用（归属会混乱）；混用会让读者分不清说话人。",
        "counterexample": "未发现明确反例",
        "evidence": [
            {"chunk_id": "c002", "quote": "“早一天晚一天有什么关系，”他拍拍手，“坐下来慢慢说。”",
             "metric": "tag_frequencies", "note": "逗号收尾接动作分句再开启下一句引语"},
            {"chunk_id": "c006", "quote": "“现在可以走了吗？”她问。",
             "metric": "tag_frequencies", "note": "标签只承担归属"},
        ],
        "transferability": "high",
        "confidence": "high",
    }
    data.update(overrides)
    return data


class TechniqueCardTest(unittest.TestCase):

    def test_valid_card_passes_schema_and_content_gate(self):
        card = TechniqueCard.from_dict(_card())
        ok, errors = card.validate()
        self.assertTrue(ok, errors)
        self.assertEqual(check_card_content_quality(_card()), ([], []))

    def test_generic_name_is_rejected(self):
        card = TechniqueCard.from_dict(_card(name="描写细腻"))
        ok, errors = card.validate()
        self.assertFalse(ok)
        self.assertTrue(any("distinctive" in e for e in errors))

    def test_steps_bounds(self):
        ok, errors = TechniqueCard.from_dict(_card(steps=["一步"])).validate()
        self.assertFalse(ok)
        self.assertTrue(any("steps count" in e for e in errors))

    def test_plot_summary_is_rejected_by_content_gate(self):
        errors, _ = check_card_content_quality(_card(
            name="异能体系工程化解构",
            definition="将神秘力量视为可控能量并嵌入工业流程。",
            steps=["摒弃神秘学定义", "用对照实验测试边界", "接入生产流水线"],
        ))
        self.assertTrue(any("行文层机制词" in e for e in errors))

    def test_vague_trigger_and_boundary_are_rejected(self):
        errors, _ = check_card_content_quality(_card(trigger="需要时", boundary="无"))
        self.assertTrue(any("触发条件" in e for e in errors))
        self.assertTrue(any("失效边界" in e for e in errors))

    def test_overlong_quote_is_rejected(self):
        errors, _ = check_card_content_quality(_card(
            evidence=[{"quote": "很长" * 60, "metric": "比喻密度", "note": "注解"}]))
        self.assertTrue(any(str(QUOTE_MAX_CHARS) in e for e in errors))

    def test_render_markdown_carries_every_contract_field(self):
        markdown = TechniqueCard.from_dict(_card()).render_markdown()
        for fragment in ("T01", "定义", "本卡服务的阅读效果", "触发条件", "写法要点",
                         "失效边界", "反例/禁忌", "迁移性 / 置信度", "证据支撑"):
            self.assertIn(fragment, markdown)


class ThinkingLayerTest(unittest.TestCase):

    def test_all_seven_dimensions_required(self):
        data = {key: "一段足够长度的机制描述。" for key in ThinkingLayer.REQUIRED_KEYS}
        self.assertEqual(ThinkingLayer.from_dict(data).validate(), (True, []))
        data.pop("long_arc")
        ok, errors = ThinkingLayer.from_dict(data).validate()
        self.assertFalse(ok)
        self.assertTrue(any("long_arc" in e for e in errors))

    def test_render_marks_all_sections(self):
        data = {key: "描述" for key in ThinkingLayer.REQUIRED_KEYS}
        markdown = ThinkingLayer.from_dict(data).render_markdown()
        for number in range(1, 8):
            self.assertIn(f"### 3.{number} ", markdown)


class WriterContractTest(unittest.TestCase):

    def test_valid_contract(self):
        contract = WriterContract.from_dict({
            "positioning": "架空武侠连载样本",
            "purpose": "读者每章至少获得一次危机推进",
            "style_marks_synthesis": "短句推进与具象比喻收束交替",
            "enemy_clauses": ["禁用修饰性标签", "禁用无场景切换的三段连写"],
        })
        self.assertEqual(contract.validate(), (True, []))
        self.assertIn("〇.4", contract.render_markdown())

    def test_missing_field_and_clause_bounds(self):
        ok, errors = WriterContract.from_dict({
            "positioning": "短", "purpose": "", "style_marks_synthesis": NOT_PROVIDED,
            "enemy_clauses": ["一条"],
        }).validate()
        self.assertFalse(ok)
        self.assertEqual(len(errors), 3, errors)

    def test_semicolon_string_is_split_into_clauses(self):
        contract = WriterContract.from_dict({
            "positioning": "定位描述", "purpose": "目的描述", "style_marks_synthesis": "综合描述",
            "enemy_clauses": "第一条禁令；第二条禁令",
        })
        self.assertEqual(len(contract.enemy_clauses), 2)


class ClaimTest(unittest.TestCase):

    def test_unknown_ids_fail_closed(self):
        normalized, errors, _ = validate_claims(
            [{"claim_id": "CL1", "category": "rhythm", "statement": "短句推进",
              "evidence_refs": ["E9999"], "confidence": 0.8}],
            {"E0001": {}}, {"M010": {}},
        )
        self.assertTrue(any("E9999" in e for e in errors))
        self.assertEqual(normalized[0]["claim_id"], "CL1")

    def test_bad_category_is_rejected(self):
        _, errors, _ = validate_claims(
            [{"claim_id": "CL1", "category": "nope", "statement": "x", "evidence_refs": ["E0001"]}],
            {"E0001": {}}, {},
        )
        self.assertTrue(any("category" in e for e in errors))

    def test_incomplete_claim_warns_not_blocks(self):
        _, errors, warnings = validate_claims(
            [{"claim_id": "CL1", "category": "rhythm", "statement": "短句推进",
              "evidence_refs": ["E0001"], "confidence": 0.5}],
            {"E0001": {}}, {},
        )
        self.assertEqual(errors, [])
        self.assertTrue(warnings)


class ReportSchemaSixTest(unittest.TestCase):
    """schema 6 的根级字段必须齐备——它们各自对应一项从 v7.0.0 恢复的能力。"""

    REQUIRED_ROOT_KEYS = (
        "version", "schema_version", "artifact_policy", "meta",
        "writer_contract", "quantitative_features", "voiceprint",
        "cross_era_matrix", "deployment_config", "style_templates",
        "technique_cards", "thinking_layer", "desensitization_map",
        "dialogue_review", "provenance", "validation_summary",
        "artifact_diagnostics",
    )

    def _report_json(self):
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        prep = fx.prepared(key="schema6")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="契约")
        return rendered["report_json"]

    def test_schema_version_is_six(self):
        from author_persona_skill.report.renderer import REPORT_SCHEMA_VERSION
        self.assertEqual(REPORT_SCHEMA_VERSION, "6")
        self.assertEqual(self._report_json()["schema_version"], "6")

    def test_root_keys_present(self):
        report_json = self._report_json()
        for key in self.REQUIRED_ROOT_KEYS:
            self.assertIn(key, report_json, key)

    def test_prepare_contract_stays_v1(self):
        """prepare 契约不随 schema 6 升版：新字段走可选键，旧 prep 仍可 finalize。"""
        from author_persona_skill.contracts import PREPARE_SCHEMA_VERSION
        self.assertEqual(PREPARE_SCHEMA_VERSION, "1")

    def test_metric_version_is_four(self):
        from author_persona_skill.report.metrics import METRIC_VERSION
        self.assertEqual(METRIC_VERSION, "4")


if __name__ == "__main__":
    unittest.main()
