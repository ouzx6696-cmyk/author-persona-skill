# -*- coding: utf-8 -*-
"""Numeric fidelity layer: placeholder registry, substitution, and claim audit."""
from __future__ import annotations

import unittest

from author_persona_skill.report.metrics import (
    CORE_AUDIT_TOKENS,
    METRIC_VERSION,
    audit_json_numeric_claims,
    audit_numeric_claims,
    build_metric_registry,
    build_placeholder_map,
    find_unresolved_metric_refs,
    find_unresolved_tokens,
    metric_token_from_label,
    metric_token_present,
    substitute_metric_refs,
    substitute_placeholders,
)

from tests import _fixtures as fx


class PlaceholderMapTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.quant = fx.prepared()["quantitative_features"]
        cls.mapping = build_placeholder_map(cls.quant)

    def test_every_core_metric_has_a_placeholder(self):
        for token in CORE_AUDIT_TOKENS:
            self.assertIn(token, self.mapping, f"core metric {token} has no placeholder")

    def test_substitution_is_total_and_leaves_unknown_tokens(self):
        text = "平均句长 {{avg_sent_len}} 字，{{unknown_token}} 保持原样。"
        out = substitute_placeholders(text, self.mapping)
        self.assertNotIn("{{avg_sent_len}}", out)
        self.assertIn(str(self.mapping["avg_sent_len"]), out)
        self.assertIn("{{unknown_token}}", out)
        self.assertEqual(find_unresolved_tokens(out), ["unknown_token"])

    def test_metric_registry_and_alias_resolution(self):
        registry = build_metric_registry(self.quant)
        self.assertTrue(registry)
        sample = registry["M010"]
        self.assertEqual(sample["token"], "avg_sent_len")
        self.assertEqual(sample["metric_version"], METRIC_VERSION)
        self.assertEqual(sample["scope"], "sample")
        self.assertEqual(substitute_metric_refs("{{metric:M010}}", registry),
                         str(sample["value"]))
        self.assertEqual(substitute_metric_refs("{{metric:avg_sent_len}}", registry),
                         str(sample["value"]))
        self.assertEqual(find_unresolved_metric_refs("{{metric:M999}}", registry), ["M999"])


class LabelResolutionTest(unittest.TestCase):

    def test_canonical_tokens_and_chinese_aliases(self):
        self.assertEqual(metric_token_from_label("punc_dash"), "punc_dash")
        self.assertEqual(metric_token_from_label("short_sent_ratio_pct"), "short_sent_ratio")
        self.assertEqual(metric_token_from_label("破折号"), "punc_dash")
        self.assertEqual(metric_token_from_label("逗句比"), "comma_period_ratio")
        self.assertIsNone(metric_token_from_label("飞天指数"))

    def test_presence_check_against_measured_features(self):
        quant = fx.prepared()["quantitative_features"]
        self.assertTrue(metric_token_present("比喻密度", quant))
        self.assertFalse(metric_token_present("飞天指数", quant))


class NumericAuditTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.quant = fx.prepared()["quantitative_features"]
        cls.mapping = build_placeholder_map(cls.quant)

    def _audit(self, line):
        return audit_numeric_claims(line, self.quant, self.mapping)

    def test_matching_value_passes(self):
        self.assertEqual(self._audit(f"平均句长 {self.mapping['avg_sent_len']} 字，节奏短促。"), [])

    def test_core_conflict_is_error(self):
        conflicts = self._audit("平均句长 99 字，节奏短促。")
        self.assertTrue(conflicts)
        self.assertEqual(conflicts[0]["severity"], "error")

    def test_minor_conflict_is_warning(self):
        conflicts = self._audit("场景切换密度 88 次/千字。")
        self.assertTrue(conflicts)
        self.assertEqual(conflicts[0]["severity"], "warning")

    def test_evidence_lines_are_exempt(self):
        self.assertEqual(self._audit("[c001] “平均句长 99 字” (平均句长)"), [])

    def test_audit_reads_the_first_number_after_the_keyword(self):
        """Documented limit: one audit hit per metric keyword per line.

        The regex binds the first number that follows the keyword, so a second
        fabricated figure later in the same clause is out of scope. Placeholder
        substitution is the primary defense; this audit is the backstop.
        """
        line = f"平均句长 {self.mapping['avg_sent_len']} 字，节奏短促。"
        self.assertEqual(self._audit(line), [])
        self.assertTrue(self._audit("平均句长 99 字，但真实值为 14 字。"))

    def test_json_walk_skips_quotes_and_mapping_but_audits_steps(self):
        payload = {
            "technique_cards": [{
                "steps": ["平均句长控制在 99 字"],
                "evidence": [{"quote": "平均句长 99 字", "note": "平均句长 99 字"}],
            }],
            "desensitization_map": {"平均句长 99 字": "标签"},
        }
        conflicts = audit_json_numeric_claims(payload, self.quant, self.mapping)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("steps", conflicts[0]["context"])


if __name__ == "__main__":
    unittest.main()
