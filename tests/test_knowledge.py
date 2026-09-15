# -*- coding: utf-8 -*-
"""知识层：维度间关联规则、风格 DNA 候选、通用 AI 味禁用词、补充量化禁令。"""
from __future__ import annotations

import unittest

from author_persona_skill.analyzers.knowledge import (
    CROSS_METRIC_RULES,
    DNA_CANDIDATES,
    GENERIC_TABOO_PHRASES,
    build_knowledge_layer,
    build_style_dna_candidates,
    evaluate_cross_metric_rules,
)
from author_persona_skill.report.renderer import extract_json_block, render_report_outputs
from author_persona_skill.report.templates import _format_knowledge_menu

from tests import _fixtures as fx


def _quant(**overrides) -> dict:
    """A quant dict shaped like the analyzer's, with explicit overrides."""
    base = {
        "sentence_structure": {"avg_sent_len": 20.0, "short_sent_ratio_pct": "20.0%",
                               "long_sent_ratio_pct": "5.0%"},
        "paragraph_rhythm": {"avg_para_len": 50.0, "short_para_ratio_pct": "10.0%"},
        "dialogue_features": {"dialogue_ratio": 0.3, "total_quotes": 200},
        "punctuation_density": {"exclamation": 1.0, "question": 1.0,
                                "ellipsis": 1.0, "dash": 1.0},
        "rhetoric_features": {"metaphor_density": 2.0},
        "description_density": {"action_count": 50, "mental_count": 30, "env_count": 20},
    }
    for section, values in overrides.items():
        base.setdefault(section, {}).update(values)
    return base


class CrossMetricRuleTest(unittest.TestCase):

    def test_all_eight_rules_defined(self):
        self.assertEqual(len(CROSS_METRIC_RULES), 8)
        self.assertEqual([r[0] for r in CROSS_METRIC_RULES],
                         ["X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"])

    def test_short_and_exclamatory_fires_x1(self):
        signals = evaluate_cross_metric_rules(_quant(
            sentence_structure={"short_sent_ratio_pct": "40%"},
            punctuation_density={"exclamation": 7.0},
        ))
        self.assertIn("X1", [s["rule_id"] for s in signals])

    def test_short_but_calm_fires_x2(self):
        signals = evaluate_cross_metric_rules(_quant(
            sentence_structure={"short_sent_ratio_pct": "40%"},
            punctuation_density={"exclamation": 0.5},
        ))
        self.assertIn("X2", [s["rule_id"] for s in signals])

    def test_rules_are_mutually_exclusive_where_designed(self):
        # X1 and X2 cannot both fire: one needs exclaim>5, the other <2.
        signals = evaluate_cross_metric_rules(_quant(
            sentence_structure={"short_sent_ratio_pct": "40%"},
            punctuation_density={"exclamation": 0.5},
        ))
        ids = [s["rule_id"] for s in signals]
        self.assertNotIn("X1", ids)

    def test_missing_inputs_skip_silently(self):
        # No vocabulary metrics yet -> X4/X5 cannot fire, but must not raise.
        signals = evaluate_cross_metric_rules(_quant())
        ids = [s["rule_id"] for s in signals]
        self.assertNotIn("X4", ids)
        self.assertNotIn("X5", ids)

    def test_vocabulary_rules_activate_when_metrics_present(self):
        quant = _quant()
        quant["vocabulary_richness"] = {"ttr": 0.6}
        quant["rhetoric_features"] = {"metaphor_density": 5.0}
        signals = evaluate_cross_metric_rules(quant)
        self.assertIn("X4", [s["rule_id"] for s in signals])

    def test_signals_carry_basis_and_are_not_authoritative(self):
        signals = evaluate_cross_metric_rules(_quant(
            sentence_structure={"short_sent_ratio_pct": "40%"},
            punctuation_density={"exclamation": 0.5},
        ))
        self.assertTrue(signals)
        for signal in signals:
            self.assertFalse(signal["authoritative"])
            self.assertTrue(signal["basis"])


class StyleDnaCandidateTest(unittest.TestCase):

    def test_all_thirteen_labels_plus_fallbacks_defined(self):
        self.assertEqual(len(DNA_CANDIDATES), 13)
        self.assertEqual(len(DNA_CANDIDATES) + 3, 16)

    def test_candidates_are_ranked_descending(self):
        quant = _quant(sentence_structure={"short_sent_ratio_pct": "40%"},
                       punctuation_density={"exclamation": 0.5})
        cands = build_style_dna_candidates(quant)
        scores = [c["score"] for c in cands]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_all_candidates_marked_non_authoritative(self):
        # 这是「派生候选」，不是分析器的裁决。
        for cand in build_style_dna_candidates(_quant()):
            self.assertFalse(cand["authoritative"])

    def test_fallback_when_nothing_matches(self):
        # 极端中性数据：阈值表全不命中，兜底给出方向性标签。
        quant = _quant(
            sentence_structure={"avg_sent_len": 25.0, "short_sent_ratio_pct": "10%"},
            punctuation_density={"exclamation": 3.0, "question": 3.0,
                                 "ellipsis": 1.0, "dash": 1.0},
        )
        cands = build_style_dna_candidates(quant)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["label"], "均衡叙事型")
        self.assertEqual(cands[0]["score"], 0.0)

    def test_deterministic_ordering(self):
        quant = _quant(sentence_structure={"short_sent_ratio_pct": "40%"},
                       punctuation_density={"exclamation": 0.5})
        self.assertEqual(build_style_dna_candidates(quant),
                         build_style_dna_candidates(quant))

    def test_missing_metric_never_produces_degenerate_label(self):
        # 无标点数据时，依赖感叹号的标签必须整体缺席而不是当成 0 参与打分。
        quant = _quant()
        quant.pop("punctuation_density")
        labels = [c["label"] for c in build_style_dna_candidates(quant)]
        self.assertNotIn("轻松搞笑型", labels)
        self.assertNotIn("热血爆发型", labels)


class GenericTabooTest(unittest.TestCase):

    def test_ten_phrases_from_archive(self):
        self.assertEqual(len(GENERIC_TABOO_PHRASES), 10)
        for phrase in ("总而言之", "综上所述", "值得注意的是", "由此可见"):
            self.assertIn(phrase, GENERIC_TABOO_PHRASES)


class KnowledgeMenuTest(unittest.TestCase):

    def test_menu_is_labeled_non_authoritative(self):
        quant = _quant(
            sentence_structure={"short_sent_ratio_pct": "40%"},
            punctuation_density={"exclamation": 0.5})
        quant["knowledge_layer"] = build_knowledge_layer(quant)
        text = _format_knowledge_menu(quant)
        self.assertIn("非结论", text)
        self.assertIn("不具权威性", text)

    def test_menu_empty_without_layer(self):
        self.assertEqual(_format_knowledge_menu({}), "")

    def test_menu_lists_taboo_phrases(self):
        """禁用词表也要进提示词菜单，否则第 5 条铁律的「AI 腔」那半条无处落地。"""
        quant = _quant()
        quant["knowledge_layer"] = build_knowledge_layer(quant)
        text = _format_knowledge_menu(quant)
        self.assertIn("通用禁用词", text)
        for phrase in GENERIC_TABOO_PHRASES:
            self.assertIn(phrase, text)

    def test_menu_renders_taboos_even_without_signals(self):
        """规则未命中时菜单仍须出现（只要禁用词在），不能整块塌成空串。"""
        quant = _quant()
        quant["knowledge_layer"] = {
            "cross_metric_signals": [],
            "style_dna_candidates": [],
            "generic_taboo_phrases": list(GENERIC_TABOO_PHRASES),
        }
        text = _format_knowledge_menu(quant)
        self.assertIn("通用禁用词", text)
        self.assertIn("总而言之", text)

    def test_prompt_carries_knowledge_menu(self):
        prep = fx.prepared(key="w4")
        self.assertIn("知识层候选", prep["llm_prompt"])
        self.assertIn("非结论", prep["llm_prompt"])
        self.assertIn("通用禁用词", prep["llm_prompt"])


class KnowledgeLayerIntegrationTest(unittest.TestCase):

    def test_layer_folded_into_quantitative_features(self):
        quant = fx.prepared(key="w4")["quantitative_features"]
        layer = quant.get("knowledge_layer")
        self.assertIsInstance(layer, dict)
        self.assertIn("cross_metric_signals", layer)
        self.assertIn("style_dna_candidates", layer)
        self.assertIn("generic_taboo_phrases", layer)

    def test_layer_is_deterministic(self):
        a = build_knowledge_layer(_quant())
        b = build_knowledge_layer(_quant())
        self.assertEqual(a, b)

    def test_layer_has_no_identity_strings(self):
        import json
        prep = fx.prepared(key="w4")
        layer = prep["quantitative_features"]["knowledge_layer"]
        blob = json.dumps(layer, ensure_ascii=False)
        for name in ("测试作者", "测试书"):
            self.assertNotIn(name, blob)


class SupplementalBansTest(unittest.TestCase):
    """归档 build_customized_taboos 里丢失的 5 条禁令 + AI 味禁用词段落。"""

    def _prompt(self) -> str:
        from author_persona_skill.persona.system_prompt import build_system_prompt
        prep = fx.prepared(key="w4-bans", options={"generate_system_prompt": True})
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="禁令")
        return build_system_prompt(rendered["report_json"])

    def test_generic_taboo_section_present(self):
        prompt = self._prompt()
        self.assertIn("通用禁用词", prompt)
        for phrase in GENERIC_TABOO_PHRASES:
            self.assertIn(phrase, prompt)

    def test_environment_ban_uses_measured_pct(self):
        # 夹具环境描写占比 57.7% > 30 -> 走「严禁省略」分支
        prompt = self._prompt()
        bans = prompt.split("## 量化禁令")[1].split("## 对话规范")[0]
        self.assertIn("环境描写", bans)
        self.assertIn("%", bans)

    def test_psych_ban_uses_measured_pct(self):
        bans = self._prompt().split("## 量化禁令")[1].split("## 对话规范")[0]
        self.assertIn("心理描写", bans)

    def test_short_rate_ban_present(self):
        bans = self._prompt().split("## 量化禁令")[1].split("## 对话规范")[0]
        self.assertIn("禁止连续 3 句以上长句", bans)

    def test_sentence_cap_ban_present(self):
        # avg_sent_len=14.4 < 18 -> 出现 25 字上限禁令
        bans = self._prompt().split("## 量化禁令")[1].split("## 对话规范")[0]
        self.assertIn("禁止单句超过 25 字", bans)

    def test_exclaim_for_question_ban_present(self):
        # question 4.39 > exclaim 1.46 * 2 -> 出现叹号代问号禁令
        bans = self._prompt().split("## 量化禁令")[1].split("## 对话规范")[0]
        self.assertIn("禁止用感叹号替代疑问表达", bans)

    def test_every_ban_carries_a_number(self):
        # 与 _assert_quantified_bans 同源的规矩：禁令必须带实测数值。
        bans = self._prompt().split("## 量化禁令")[1].split("## 对话规范")[0]
        for line in bans.splitlines():
            if line.startswith("- ") and "未知" not in line:
                self.assertRegex(line, r"\d", f"禁令缺少数值: {line}")


if __name__ == "__main__":
    unittest.main()
