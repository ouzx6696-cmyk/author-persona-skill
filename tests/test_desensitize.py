# -*- coding: utf-8 -*-
"""Desensitization: narrow candidate sources, masking, and reverse leak checks."""
from __future__ import annotations

import unittest

from author_persona_skill.distill.desensitize import (
    apply_desensitization,
    build_forbidden_identities,
    compute_work_id,
    extract_proper_noun_candidates,
    mask_evidence_quotes,
    scan_artifact,
    validate_desensitization,
    validate_desensitization_map,
)

from tests import _fixtures as fx


class CandidateExtractionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()

    def test_candidates_come_from_narrow_sources_only(self):
        types = {c["suggested_type"] for c in self.prep["proper_noun_candidates"]}
        self.assertTrue(types <= {"author_identity", "work_identity", "character", "worldview_term"}, types)
        terms = [c["term"] for c in self.prep["proper_noun_candidates"]]
        self.assertIn("测试作者", terms)
        self.assertIn("测试书", terms)
        self.assertLessEqual(len(terms), 50)

    def test_speaker_candidates_use_dialogue_analyzer_authority(self):
        speakers = self.prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]
        self.assertTrue(speakers)
        top = max(speakers, key=lambda s: s["occurrences"])["name"]
        self.assertIn(top, [c["term"] for c in self.prep["proper_noun_candidates"]])

    def test_whitelist_words_are_not_candidates(self):
        terms = {c["term"] for c in self.prep["proper_noun_candidates"]}
        self.assertFalse(terms & {"说道", "问道", "自己", "什么"})


class MappingApplicationTest(unittest.TestCase):

    def test_longest_first_without_cascades(self):
        mapping = {"角色甲": "继承者", "角色": "某某"}
        self.assertEqual(apply_desensitization("角色甲走过", mapping), "继承者走过")

    def test_identity_mapping_is_rejected(self):
        errors, _ = validate_desensitization_map({"角色甲": "角色甲"}, [{"term": "角色甲"}])
        self.assertTrue(any(e["type"] == "identity_mapping" for e in errors))

    def test_mapping_outside_candidates_warns(self):
        errors, warnings = validate_desensitization_map({"外来词": "原型丙"}, [{"term": "角色甲"}])
        self.assertFalse(errors)
        self.assertTrue(any(w["type"] == "mapping_not_in_candidates" for w in warnings))


class EvidenceMaskingTest(unittest.TestCase):

    def test_quotes_are_hidden_but_metadata_survives(self):
        line = "[c001] “这是一段原文引用，必须被遮蔽。” (比喻密度) — 注解：该句体现单句点染。"
        masked = mask_evidence_quotes(line, "已隐藏")
        self.assertIn("[c001]", masked)
        self.assertIn("已隐藏", masked)
        self.assertIn("比喻密度", masked)
        self.assertIn("注解：该句体现单句点染。", masked)
        self.assertNotIn("必须被遮蔽", masked)

    def test_second_quote_on_same_line_is_also_masked(self):
        """Every quoted span before the annotation boundary is hidden.

        The annotation itself is LLM metadata (the guide's own examples quote
       喻体 words there), so it survives masking and is covered by the noun
        mapping plus the leak scanner instead.
        """
        line = "[c001] “第一段引用内容。” (比喻密度) — 注解：注解里再次出现“第二段引用内容”。"
        masked = mask_evidence_quotes(line, "已隐藏")
        self.assertNotIn("第一段引用内容", masked)
        self.assertIn("注解：注解里再次出现", masked)


class ReverseValidationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()
        cls.candidates = cls.prep["proper_noun_candidates"]

    def test_clean_body_passes(self):
        passed, leaks = validate_desensitization(
            "正文只谈行文机制，不含任何专名。", self.candidates, "测试作者", "测试书")
        self.assertTrue(passed, leaks)

    def test_identity_leak_blocks(self):
        passed, leaks = validate_desensitization(
            "测试作者的笔法。", self.candidates, "测试作者", "测试书")
        self.assertFalse(passed)
        self.assertTrue(any(l["type"] == "author_identity_leak" for l in leaks))

    def test_evidence_quote_line_is_exempt(self):
        line = f"[c001] “{self.candidates[2]['term']}出现在引文里。” (比喻密度)"
        passed, _ = validate_desensitization(line, self.candidates, "测试作者", "测试书")
        self.assertTrue(passed)

    def test_scan_artifact_exempts_quote_and_mapping_keys(self):
        data = {
            "technique_cards": [{"evidence": [{"quote": "苏疏的引文"}]}],
            "desensitization_map": {"苏疏": "原型甲"},
            "thinking_layer": {"closure": "苏疏的名字不该出现在这里。"},
        }
        leaks = scan_artifact(data, self.candidates, "测试作者", "测试书")
        self.assertEqual(len(leaks), 1)
        self.assertIn("thinking_layer", leaks[0]["path"])

    def test_forbidden_identities_always_include_author_and_title(self):
        terms = build_forbidden_identities([], "作者名", "作品名")
        self.assertIn("作者名", terms)
        self.assertIn("作品名", terms)


class WorkIdTest(unittest.TestCase):

    def test_stable_and_pseudonymous(self):
        first = compute_work_id("测试作者", "测试书")
        self.assertEqual(first, compute_work_id("测试作者", "测试书"))
        self.assertTrue(first.startswith("WORK_"))
        self.assertNotIn("测试", first)
        self.assertEqual(compute_work_id("", ""), "WORK_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
