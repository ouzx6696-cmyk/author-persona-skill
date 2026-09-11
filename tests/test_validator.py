# -*- coding: utf-8 -*-
"""Validator gates: each contract violation must block, each soft issue must warn."""
from __future__ import annotations

import unittest

from author_persona_skill.report.renderer import extract_json_block
from author_persona_skill.report.validator import validate_report

from tests import _fixtures as fx


def _validate(response: str, prep=None):
    prep = prep or fx.prepared()
    prose, data = extract_json_block(response)
    return validate_report(prose_markdown=prose, parsed_json=data, prepare_result=prep)


class ValidatorHappyPathTest(unittest.TestCase):

    def test_valid_response_passes_every_gate(self):
        result = _validate(fx.valid_response(fx.prepared()))
        self.assertEqual(result["status"], "passed", result["errors"])
        self.assertEqual(result["schema"], "passed")
        self.assertEqual(result["desensitization"], "passed")
        self.assertEqual(result["numeric_audit"]["status"], "passed")
        self.assertEqual(result["evidence"]["valid"] + result["evidence"]["fixed"], 6)
        self.assertEqual(result["evidence"]["cross_era_status"], "passed")


class CardGateTest(unittest.TestCase):

    def _mutate_first_card(self, mutate):
        response = fx.valid_response(fx.prepared())
        return fx.mutate_json(response, lambda d: mutate(d["technique_cards"][0]))

    def test_missing_note_blocks(self):
        result = _validate(self._mutate_first_card(lambda c: c["evidence"][0].pop("note")))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("note" in e for e in result["errors"]))

    def test_missing_serves_purpose_blocks(self):
        result = _validate(self._mutate_first_card(lambda c: c.pop("serves_purpose")))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("serves_purpose" in e for e in result["errors"]))

    def test_plot_summary_card_blocks(self):
        def mutate(card):
            card["name"] = "异能体系工程化解构"
            card["definition"] = "将神秘力量视为可控能量，用现代科学原理定量分类并嵌入工业流程。"
            card["steps"] = ["摒弃神秘学定义", "用对照实验测试边界", "接入生产流水线"]

        result = _validate(self._mutate_first_card(mutate))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("行文层机制词" in e for e in result["errors"]))

    def test_hallucinated_quote_is_downgraded_then_blocks(self):
        def mutate(card):
            for ev in card["evidence"]:
                ev.pop("evidence_id", None)
                ev["quote"] = "这句话在语料里根本不存在，纯属编造出来的锚点内容。"

        result = _validate(self._mutate_first_card(mutate))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("严格命中的证据不足" in e for e in result["errors"]))

    def test_unknown_evidence_id_blocks(self):
        result = _validate(self._mutate_first_card(lambda c: c["evidence"][0].update({"evidence_id": "E9999"})))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("证据ID不存在" in e for e in result["errors"]))

    def test_metric_label_must_resolve_to_measured_field(self):
        result = _validate(self._mutate_first_card(lambda c: c["evidence"][0].update({"metric": "飞天指数"})))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("无法解析" in e or "未出现" in e for e in result["errors"]))

    def test_card_count_bounds(self):
        result = _validate(fx.mutate_json(fx.valid_response(fx.prepared()),
                                          lambda d: d["technique_cards"].pop()))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("技法卡数量" in e for e in result["errors"]))

    def test_cross_era_requirement_is_per_card(self):
        """One card must itself hold two different eras, not the report in total."""
        prep = fx.prepared()

        def mutate(data):
            # Collapse every card's evidence onto the first era seen.
            era = None
            for card in data["technique_cards"]:
                for ev in card["evidence"]:
                    unit = prep["evidence_store_ids"].get(str(ev.get("evidence_id", "")), {})
                    if era is None and unit.get("era"):
                        era = unit["era"]
            same_era = [
                unit["evidence_id"] for unit in prep["evidence_store_ids"].values()
                if unit.get("era") == era
            ][:2]
            for index, card in enumerate(data["technique_cards"]):
                for position, ev in enumerate(card["evidence"]):
                    eid = same_era[(index + position) % len(same_era)]
                    unit = prep["evidence_store_ids"][eid]
                    ev.update({"evidence_id": eid, "chunk_id": unit["chunk_id"],
                               "quote": unit["text"], "era": era})

        result = _validate(fx.mutate_json(fx.valid_response(prep), mutate), prep)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("两个不同时期" in e for e in result["errors"]))


class ContractGateTest(unittest.TestCase):

    def test_missing_writer_contract_blocks(self):
        result = _validate(fx.mutate_json(fx.valid_response(fx.prepared()),
                                          lambda d: d.pop("writer_contract")))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("writer_contract" in e for e in result["errors"]))

    def test_enemy_clause_bounds(self):
        result = _validate(fx.mutate_json(
            fx.valid_response(fx.prepared()),
            lambda d: d["writer_contract"].update({"enemy_clauses": ["只有一条"]}),
        ))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("enemy_clauses" in e for e in result["errors"]))

    def test_thinking_layer_requires_all_dimensions(self):
        result = _validate(fx.mutate_json(fx.valid_response(fx.prepared()),
                                          lambda d: d["thinking_layer"].pop("closure")))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("closure" in e for e in result["errors"]))


class PrivacyGateTest(unittest.TestCase):

    def test_unmapped_candidate_in_prose_blocks(self):
        prep = fx.prepared()

        def mutate(data):
            data["desensitization_map"].pop("苏疏", None)

        response = fx.mutate_json(fx.valid_response(prep), mutate)
        prose, json_data = extract_json_block(response)
        response = prose.replace("### 1.9 小节标题", "### 1.9 小节标题\n苏疏的声纹与对手原型形成对照。")
        response += "\n\n```json\n" + __import__("json").dumps(json_data, ensure_ascii=False) + "\n```\n"
        result = _validate(response, prep)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("脱敏" in e for e in result["errors"]))

    def test_author_identity_in_prose_blocks_when_unmapped(self):
        prep = fx.prepared()
        response = fx.mutate_json(
            fx.valid_response(prep),
            lambda d: d["desensitization_map"].pop("测试作者", None),
        ).replace("### 1.1 小节标题", "### 1.1 小节标题\n测试作者的笔法值得注意。")
        result = _validate(response, prep)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("测试作者" in e for e in result["errors"]))


class NumericAuditTest(unittest.TestCase):

    def test_core_metric_conflict_blocks(self):
        response = fx.valid_response(fx.prepared()).replace(
            "平均句长 {{avg_sent_len}} 字", "平均句长 99 字")
        result = _validate(response)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("数值审计冲突" in e for e in result["errors"]))

    def test_minor_metric_conflict_only_warns(self):
        response = fx.valid_response(fx.prepared()).replace(
            "场景切换密度 {{scene_switch_density}} 次/千字", "场景切换密度 88 次/千字")
        result = _validate(response)
        self.assertEqual(result["status"], "passed", result["errors"])
        self.assertTrue(any("数值偏差提示" in w for w in result["warnings"]))

    def test_json_step_text_is_audited_too(self):
        def mutate(data):
            data["technique_cards"][0]["steps"][0] = "平均句长必须写成 99 字"

        result = _validate(fx.mutate_json(fx.valid_response(fx.prepared()), mutate))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("数值审计冲突" in e for e in result["errors"]))


class QualityAssessmentTest(unittest.TestCase):

    def test_quality_is_reported_but_does_not_change_status(self):
        result = _validate(fx.valid_response(fx.prepared()))
        self.assertIn(result["quality_status"], {"passed", "failed"})
        self.assertEqual(result["publishable"], "passed" if result["quality_status"] == "passed" else "failed")

    def test_shallow_sections_mark_publishable_failed(self):
        response = fx.valid_response(fx.prepared()).replace(
            fx._LONG_SECTIONS["1.2"], "平均句长 {{avg_sent_len}} 字。")
        result = _validate(response)
        self.assertEqual(result["status"], "passed", result["errors"])
        self.assertEqual(result["quality_status"], "failed")
        self.assertTrue(any("1.2" in reason for reason in result["quality"]["reasons"]))


if __name__ == "__main__":
    unittest.main()
