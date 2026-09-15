# -*- coding: utf-8 -*-
"""角色话术建模：实测字段、公开脱敏话术块、dialogue_review 校验闸门。

这个模块同时是 W2 的防回归锁：旧版 v7.0.0 有完整的角色话术建模，迭代中被静默
删除后没有任何用例发现，直到对照归档版才被找回。以下每个断言对应一项曾被丢失
的能力。
"""
from __future__ import annotations

import json
import unittest

from author_persona_skill.analyzers.dialogue_analyzer import DialogueAnalyzer
from author_persona_skill.report.renderer import extract_json_block, render_report_outputs
from author_persona_skill.report.validator import validate_report

from tests import _fixtures as fx


class ToneClassificationTest(unittest.TestCase):
    """tone_type：问号占比>0.3→疑问型；叹号占比>0.2→命令型；否则陈述型。"""

    def setUp(self):
        self.analyzer = DialogueAnalyzer()

    def test_question_dominant_is_interrogative(self):
        quotes = ["当真？", "为何？", "岂能如此？", "莫非不成？", "且慢。"]
        self.assertEqual(self.analyzer._classify_tone(quotes), "疑问型")

    def test_exclamation_dominant_is_imperative(self):
        quotes = ["站住！", "退下！", "不可！", "当真如此！", "明白了。"]
        self.assertEqual(self.analyzer._classify_tone(quotes), "命令型")

    def test_plain_statements_are_declarative(self):
        quotes = ["我知道了。", "明日出发。", "此事作罢。"]
        self.assertEqual(self.analyzer._classify_tone(quotes), "陈述型")

    def test_empty_quotes_defaults_to_declarative(self):
        self.assertEqual(self.analyzer._classify_tone([]), "陈述型")


class FixedPhraseExtractionTest(unittest.TestCase):
    """fixed_phrases/opening_words：复现归档版的最小频次门槛。"""

    def setUp(self):
        self.analyzer = DialogueAnalyzer()

    def test_short_quote_list_yields_no_phrases(self):
        # min_freq = max(2, n//10)：单条台词不可能达到 2 次，必须返回空。
        self.assertEqual(self.analyzer._extract_fixed_phrases(["只有一句"]), [])

    def test_repeated_phrase_is_extracted(self):
        quotes = ["当真如此", "当真罢了", "当真不成", "当真可以"]
        phrases = self.analyzer._extract_fixed_phrases(quotes)
        self.assertIn("当真", phrases)

    def test_opening_words_need_repeat(self):
        # min_freq = max(2, total//15)：15 条以上才开始收录首词。
        once = ["且慢。", "当真。", "不可。"]
        self.assertEqual(self.analyzer._count_opening_words(once), [])
        repeated = ["且慢。"] * 4 + ["当真。"] * 4 + ["不可。"] * 4 + ["x"] * 4
        self.assertIn("且慢", self.analyzer._count_opening_words(repeated))

    def test_output_is_capped_at_ten(self):
        quotes = [f"词{i}啊" for i in range(30)] * 3
        self.assertLessEqual(len(self.analyzer._extract_fixed_phrases(quotes)), 10)


class SpeakerProfileFieldTest(unittest.TestCase):
    """每个说话人档案必须携带可支撑 1.9 与 dialogue_review 的实测字段。"""

    @classmethod
    def setUpClass(cls):
        cls.features = fx.prepared(key="voiceprint")["quantitative_features"]["dialogue_features"]
        cls.profiles = {
            p["name"]: p for p in cls.features["high_confidence_speakers"]
        }

    def test_profiles_carry_all_voiceprint_fields(self):
        self.assertTrue(self.profiles, "语料应能识别出至少一名高置信说话人")
        for name, profile in self.profiles.items():
            with self.subTest(speaker=name):
                for field in ("tone_type", "common_tags", "fixed_phrases", "opening_words"):
                    self.assertIn(field, profile)

    def test_common_tags_are_real_tags(self):
        for profile in self.profiles.values():
            for tag in profile["common_tags"]:
                self.assertIn(tag, self.features["tag_frequencies"])

    def test_unique_tags_expose_single_owner_only(self):
        # unique_tags 记录「只有该角色用过」的标签，是私有诊断信号。
        for tag, info in self.features["unique_tags"].items():
            self.assertIn("speaker", info)
            self.assertIn("count", info)
            self.assertEqual(info["count"], self.features["tag_frequencies"].get(tag))


class PublicVoiceprintTest(unittest.TestCase):
    """公开 voiceprint 块：原型标签为键，零身份泄漏。"""

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared(key="voiceprint")
        prose, data = extract_json_block(fx.valid_response(cls.prep))
        cls.rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=cls.prep,
            base_name="话术报告")
        cls.voiceprint = cls.rendered["report_json"].get("voiceprint", {})

    def test_block_is_present_and_keyed_by_archetype(self):
        self.assertTrue(self.voiceprint, "公开产物必须携带实测话术块")
        for label in self.voiceprint:
            self.assertTrue(label.startswith("原型"), f"键必须是原型标签，实为 {label}")

    def test_block_carries_measured_fields(self):
        for label, vp in self.voiceprint.items():
            with self.subTest(label=label):
                self.assertIn(vp.get("tone_type"), {"陈述型", "疑问型", "命令型", "未定"})
                self.assertIn("common_tags", vp)
                self.assertIn("catchphrases", vp)

    def test_no_speaker_name_leaks_into_public_json(self):
        blob = json.dumps(self.rendered["report_json"], ensure_ascii=False)
        speakers = self.prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]
        for speaker in speakers:
            self.assertNotIn(speaker["name"], blob)
        self.assertNotIn("测试作者", blob)
        self.assertNotIn("测试书", blob)

    def test_private_sidecar_still_hides_raw_speaker_lists(self):
        # 结构化最小化在任何策略下都生效：说话人名单不进机器 sidecar。
        quant = self.rendered["report_json"]["quantitative_features"]["dialogue_features"]
        self.assertNotIn("high_confidence_speakers", quant)
        self.assertNotIn("unique_tags", quant)
        self.assertNotIn("low_confidence_candidates", quant)

    def test_raw_mode_uses_neutral_labels_not_real_names(self):
        prep = fx.prepared(key="raw-mode", options={"desensitize": False})
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="原始报告")
        blob = json.dumps(rendered["report_json"], ensure_ascii=False)
        for speaker in prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]:
            self.assertNotIn(speaker["name"], blob)


class DialogueReviewGateTest(unittest.TestCase):
    """dialogue_review 此前只有契约、没有闸门；这里锁定三道检查。"""

    def _validate_mutated(self, mutate):
        prep = fx.prepared()
        response = fx.valid_response(prep)
        prose, data = extract_json_block(response)
        mutated = json.loads(json.dumps(data))
        mutate(mutated)
        return validate_report(prose_markdown=prose, parsed_json=mutated, prepare_result=prep)

    def test_valid_profiles_pass(self):
        result = self._validate_mutated(lambda d: None)
        self.assertEqual(result["status"], "passed", result["errors"])

    def test_empty_profiles_block_when_speakers_measured(self):
        measured = fx.prepared()["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]
        self.assertGreaterEqual(len(measured), 2, "夹具应有多名高置信说话人")
        result = self._validate_mutated(
            lambda d: d["dialogue_review"].__setitem__("confirmed_profiles", []))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("confirmed_profiles 为空" in e for e in result["errors"]))

    def test_empty_tone_blocks(self):
        result = self._validate_mutated(
            lambda d: d["dialogue_review"]["confirmed_profiles"][0].__setitem__("tone", ""))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("tone" in e for e in result["errors"]))

    def test_unmapped_real_name_as_role_blocks(self):
        result = self._validate_mutated(
            lambda d: d["dialogue_review"]["confirmed_profiles"][0].__setitem__("role", "苏疏"))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("不是脱敏映射给出的原型标签" in e for e in result["errors"]))

    def test_missing_dialogue_review_blocks(self):
        result = self._validate_mutated(lambda d: d.pop("dialogue_review"))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("dialogue_review" in e for e in result["errors"]))


class PersonaVoiceSectionTest(unittest.TestCase):
    """分身提示词的「角色声音参考」必须改用实测 tone_type/话术。"""

    def test_persona_renders_measured_voiceprint(self):
        from author_persona_skill.persona.system_prompt import build_system_prompt
        prep = fx.prepared(key="persona-voice")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="人格")
        prompt = build_system_prompt(rendered["report_json"])
        self.assertIn("角色声音参考", prompt)
        self.assertIn("口吻类型", prompt)
        for speaker in prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]:
            self.assertNotIn(speaker["name"], prompt)


if __name__ == "__main__":
    unittest.main()
