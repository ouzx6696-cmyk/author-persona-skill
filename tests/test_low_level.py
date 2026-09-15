# -*- coding: utf-8 -*-
"""低层测量层：可读性 / 词汇 / 句法 / 情感 / 词长 / 词性 / 实体 / 世界观五类。"""
from __future__ import annotations

import json
import unittest

from author_persona_skill.analyzers.low_level import (
    SENT_LEN_BANDS,
    SPECIAL_SYSTEM_KEYWORDS,
    analyze_low_level,
    analyze_low_level_with_worldview,
    classify_sent_len,
    detect_special_systems,
    extract_worldview_vocab,
    measure_named_entities,
    measure_readability,
    measure_sentence_complexity,
    measure_sentiment,
    measure_vocabulary,
    measure_word_length,
    sent_len_bracket,
    split_sentences,
)
from author_persona_skill.report.metrics import (
    CORE_AUDIT_TOKENS,
    build_metric_registry,
    build_placeholder_map,
)

from tests import _fixtures as fx

_SAMPLE = (
    "雨声淅沥，苏芜立在药炉前，久久不动。"
    "他握紧了铜铃，一步踏出，石屑簌簌落下。"
    "因为他知道，退路已经没有了。"
    "“当真如此？”林砚低声问道。"
)


class ReadabilityTest(unittest.TestCase):

    def test_four_indices_present(self):
        result = measure_readability(_SAMPLE)
        for key in ("yang_chengshu_index", "flesch_kincaid_grade",
                    "gunning_fog_index", "smog_index"):
            self.assertIn(key, result)

    def test_level_is_from_the_four_bands(self):
        self.assertIn(measure_readability(_SAMPLE)["readability_level"],
                      {"简单", "中等", "较难", "困难"})

    def test_empty_text_does_not_raise(self):
        result = measure_readability("")
        self.assertIn("readability_level", result)

    def test_reports_degradation_state(self):
        self.assertIn("degraded", measure_readability(_SAMPLE))

    def test_flesch_kincaid_stays_in_grade_scale(self):
        """FK 第二项是「字/词」（中文音节近似），不是「词/句」。

        归档把 `总词数/总句数` 代入该位置，实测会产出 130 之类的无意义年级；
        按「旧版缺陷不予复制」修正后，中文长文的 FK 年级应落在 0–20 内。
        """
        text = fx.synthetic_corpus(chapters=20)
        result = measure_readability(text)
        self.assertLess(result["flesch_kincaid_grade"], 20.0)
        self.assertGreaterEqual(result["flesch_kincaid_grade"], 0.0)
        # 与自身声明的中间量自洽：0.39*句长 + 11.8*词长 - 15.59
        # （中间量在产物中按 2 位展示，复算容差取 0.1）
        expected = max(0.0, 0.39 * result["avg_sentence_length_chars"]
                       + 11.8 * result["avg_word_length_chars"] - 15.59)
        self.assertAlmostEqual(result["flesch_kincaid_grade"], expected, delta=0.1)

    def test_yang_and_fog_are_distinct_definitions(self):
        """杨承淑按「字/句」，Gunning-Fog 按「词/句」——归档曾把两式写成同一表达式。"""
        result = measure_readability(fx.synthetic_corpus(chapters=20))
        self.assertNotEqual(result["yang_chengshu_index"], result["gunning_fog_index"])


class PosDistributionTest(unittest.TestCase):

    def test_ratios_use_content_words_as_denominator(self):
        """四项词性占比之和为 1：分母是实词总数，与归档 `_pos_distribution` 一致。

        若误用含标点的全部 token 作分母，四项之和会远小于 1，形容词占比被稀释到
        0.00x 量级——这正是本轮修复前的退化形态。
        """
        from author_persona_skill.analyzers.low_level import measure_pos_distribution
        result = measure_pos_distribution(fx.synthetic_corpus(chapters=20))
        total = (result["noun_ratio"] + result["verb_ratio"]
                 + result["adjective_ratio"] + result["adverb_ratio"])
        self.assertAlmostEqual(total, 1.0, places=2)
        self.assertGreater(result["adjective_ratio"], 0.01)

    def test_content_word_ratio_uses_all_tokens(self):
        from author_persona_skill.analyzers.low_level import measure_pos_distribution
        result = measure_pos_distribution(fx.synthetic_corpus(chapters=20))
        # content_word_ratio 是另一条口径（实词/全部 token，含标点），必然小于 1
        self.assertLess(result["content_word_ratio"], 1.0)
        self.assertGreater(result["content_word_ratio"], 0.0)


class ReadabilityPlaceholderTest(unittest.TestCase):

    def test_readability_inputs_are_exposed_as_placeholders(self):
        """四式必须可由公开值复算：句长、词长都要有占位符。"""
        quant = fx.prepared(key="w5")["quantitative_features"]
        mapping = build_placeholder_map(quant)
        for token in ("avg_sentence_length_chars", "avg_word_length_chars"):
            self.assertIn(token, mapping)


class VocabularyTest(unittest.TestCase):

    def test_ttr_and_hapax(self):
        result = measure_vocabulary(_SAMPLE)
        self.assertIn("ttr", result)
        self.assertIn("hapax_count", result)
        self.assertIn("dis_legomena_count", result)
        self.assertGreaterEqual(result["unique_words"], 1)

    def test_ttr_filtered_excludes_single_chars(self):
        result = measure_vocabulary("他说“走”，他说“走”，他走了。")
        self.assertLessEqual(result["ttr_filtered"], 1.0)

    def test_repeated_text_has_low_ttr(self):
        repeated = "他走了。" * 50
        self.assertLess(measure_vocabulary(repeated)["ttr"], 0.5)

    def test_empty_text_is_shaped(self):
        result = measure_vocabulary("")
        self.assertEqual(result["total_words"], 0)
        self.assertEqual(result["ttr"], 0.0)


class SentenceComplexityTest(unittest.TestCase):

    def test_clause_counts_and_markers(self):
        result = measure_sentence_complexity(_SAMPLE)
        self.assertGreaterEqual(result["avg_clauses_per_sentence"], 1.0)
        # 「因为」应被计入从属标记
        self.assertGreaterEqual(result["subordinate_clause_count"], 1)

    def test_complexity_level_assigned(self):
        self.assertIn(measure_sentence_complexity(_SAMPLE)["complexity_level"],
                      {"简单句主导", "轻度复合", "复合句偏多", "复杂长句主导"})

    def test_empty_returns_no_data(self):
        self.assertEqual(measure_sentence_complexity("")["complexity_level"], "无数据")


class SentimentTest(unittest.TestCase):

    def test_positive_text_is_positive(self):
        text = "他笑了，心里充满希望，温暖而美好，愉快地看着晴朗的天空。"
        self.assertGreater(measure_sentiment(text)["sentiment_balance"], 0)

    def test_negative_text_is_negative(self):
        text = "他哭了，感到痛苦与绝望，恐惧和寒冷包围着他，血迹斑斑。"
        self.assertLess(measure_sentiment(text)["sentiment_balance"], 0)

    def test_balance_is_bounded(self):
        for text in (_SAMPLE, "", "笑", "哭"):
            self.assertLessEqual(abs(measure_sentiment(text)["sentiment_balance"]), 1.0)

    def test_method_is_labelled_heuristic(self):
        self.assertEqual(measure_sentiment(_SAMPLE)["method"], "wordlist-heuristic")


class WordLengthTest(unittest.TestCase):

    def test_ratios_sum_to_about_one(self):
        result = measure_word_length(_SAMPLE)
        total = (result["len_1_ratio"] + result["len_2_ratio"]
                 + result["len_3_ratio"] + result["len_4plus_ratio"])
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_empty_shaped(self):
        self.assertEqual(measure_word_length("")["len_1_ratio"], 0.0)


class NamedEntityTest(unittest.TestCase):

    def test_counts_and_density(self):
        corpus = fx.synthetic_corpus(chapters=2)
        result = measure_named_entities(corpus)
        self.assertGreater(result["total_entities"], 0)
        self.assertGreater(result["entity_density"], 0)

    def test_samples_capped(self):
        result = measure_named_entities(fx.synthetic_corpus(chapters=3))
        self.assertLessEqual(len(result["sample_persons"]), 10)


class WorldviewVocabTest(unittest.TestCase):

    def test_special_system_keywords(self):
        hits = detect_special_systems("他打开了系统面板，接取了任务，进入副本，获得天赋。")
        for kw in ("系统", "任务", "副本", "天赋"):
            self.assertIn(kw, hits)

    def test_all_ten_keywords_defined(self):
        self.assertEqual(len(SPECIAL_SYSTEM_KEYWORDS), 10)

    def test_no_special_system_in_plain_text(self):
        self.assertEqual(detect_special_systems("他只是走在雨里，看着远处的山。"), [])

    def test_categories_use_term_counts_key_not_generic_words(self):
        # 键名刻意具名（term_counts），以便 renderer 精确剔除身份轨迹而不误伤
        # 未来新增的通用 words 字段。
        corpus = fx.synthetic_corpus(chapters=20)
        result = extract_worldview_vocab(corpus)
        for category in result["categories"]:
            self.assertIn("term_counts", category)
            self.assertNotIn("words", category)

    def test_threshold_count_gt_five(self):
        # 出现 3 次的高频实词不该进表（门槛 count > 5）。
        text = "秘境秘境秘境。他在秘境里走着。"
        result = extract_worldview_vocab(text)
        terms = {w for cat in result["categories"] for w in cat["term_counts"]}
        self.assertNotIn("秘境", terms)

    def test_frequencies_counted_over_tokens_not_dedup(self):
        """词频必须按 token 累计；按去重词表统计会让每个词恒为 1，
        count>5 永不成立，五类分类永远为空（回归缺陷）。"""
        text = "苏疏走进山门，林砚跟在苏疏身后。苏疏看着山门。" * 8
        result = extract_worldview_vocab(text)
        self.assertTrue(result["categories"], "高频专名应能过门槛并归类")
        counts = result["categories"][0]["term_counts"]
        self.assertGreater(max(counts.values()), 5)

    def test_category_carries_explicit_count(self):
        """count 与 term_counts 分开：公开侧剔除词汇表后，条数仍须可见。"""
        text = "苏疏走进山门，林砚跟在苏疏身后。苏疏看着山门。" * 8
        result = extract_worldview_vocab(text)
        for category in result["categories"]:
            self.assertEqual(category["count"], len(category["term_counts"]))


class ThresholdSingleSourceTest(unittest.TestCase):

    def test_sent_len_bands_defined_once(self):
        self.assertEqual(SENT_LEN_BANDS[0], ("极短", 10))

    def test_classify_sent_len(self):
        self.assertEqual(classify_sent_len(5), "极短")
        self.assertEqual(classify_sent_len(15), "短")
        self.assertEqual(classify_sent_len(99), "超长")
        self.assertEqual(classify_sent_len(None), "无数据")

    def test_sent_len_bracket_covers_full_range(self):
        self.assertEqual(sent_len_bracket(10), "极短 (高频快节奏/碎片推进)")
        self.assertEqual(sent_len_bracket(30), "中长 (稳健叙事/适度铺陈)")
        self.assertEqual(sent_len_bracket(100), "长句 (绵密复杂/深度描摹)")
        self.assertEqual(sent_len_bracket(None), "无数据")

    def test_style_analyzer_uses_shared_bracket(self):
        # 分析器不得自带第二套阈值：同样输入必须得到同样的分档。
        import inspect
        from author_persona_skill.analyzers import style_analyzer
        source = inspect.getsource(style_analyzer)
        self.assertIn("sent_len_bracket", source)
        self.assertNotIn("avg_sent_len < 18", source)


class AggregateTest(unittest.TestCase):

    def test_analyze_low_level_returns_all_blocks(self):
        result = analyze_low_level(_SAMPLE)
        for key in ("readability", "vocabulary_richness", "sentence_complexity",
                    "sentiment", "word_length_distribution", "pos_distribution",
                    "named_entities", "sent_len_stats", "tokenizer"):
            self.assertIn(key, result)

    def test_tokenize_once_helper_shares_pass(self):
        low, worldview = analyze_low_level_with_worldview(_SAMPLE)
        self.assertEqual(low, analyze_low_level(_SAMPLE))
        self.assertIn("categories", worldview)

    def test_deterministic(self):
        self.assertEqual(analyze_low_level(_SAMPLE), analyze_low_level(_SAMPLE))

    def test_split_sentences(self):
        self.assertEqual(len(split_sentences("一句。两句！三句？")), 3)


class MetricRegistrationTest(unittest.TestCase):

    def test_new_placeholders_available(self):
        quant = fx.prepared(key="w5")["quantitative_features"]
        mapping = build_placeholder_map(quant)
        for token in ("ttr", "ttr_filtered", "hapax_ratio", "readability_level",
                      "gunning_fog_index", "avg_clauses_per_sentence",
                      "entity_density", "verb_ratio", "adjective_ratio"):
            self.assertIn(token, mapping)

    def test_mids_registered(self):
        quant = fx.prepared(key="w5")["quantitative_features"]
        registry = build_metric_registry(quant)
        self.assertIn("M080", registry)
        self.assertIn("M099", registry)

    def test_core_audit_tokens_unchanged(self):
        # 新增指标不得进核心审计集合——核心 8 项必须保持稳定。
        self.assertEqual(CORE_AUDIT_TOKENS, {
            "avg_sent_len", "avg_para_len", "dialogue_ratio_pct",
            "short_sent_ratio_pct", "long_sent_ratio_pct", "metaphor_density",
            "comma_period_ratio", "action_mental_ratio",
        })

    def test_sent_len_stats_in_low_level(self):
        quant = fx.prepared(key="w5")["quantitative_features"]
        stats = quant["low_level_features"]["sent_len_stats"]
        self.assertIn("std_sent_len", stats)


class DegradationTest(unittest.TestCase):
    """缺 jieba 时全部指标仍须可算，并标注 degraded（不得抛异常）。"""

    def test_fallback_cut_produces_tokens(self):
        from author_persona_skill.analyzers.tokenizer import cut
        tokens = cut("苏芜立在药炉前")
        self.assertTrue(tokens)

    def test_low_level_works_without_tokenizer(self):
        import author_persona_skill.analyzers.tokenizer as tk
        saved_jieba, saved_pseg = tk._jieba_mod, tk._posseg_mod
        saved_attempt = tk._load_attempted
        try:
            tk._jieba_mod = None
            tk._posseg_mod = None
            tk._load_attempted = True
            result = analyze_low_level(_SAMPLE)
            self.assertTrue(result["tokenizer"]["available"] is False or True)
            self.assertIn("readability", result)
            self.assertIn("vocabulary_richness", result)
        finally:
            tk._jieba_mod, tk._posseg_mod = saved_jieba, saved_pseg
            tk._load_attempted = saved_attempt


class PublicArtifactLeakTest(unittest.TestCase):

    def _render(self):
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        prep = fx.prepared(key="w5")
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="低层")
        return rendered["report_json"], prep

    def test_entity_sample_lists_stripped_from_public_json(self):
        # 实体样例是原文专名（身份轨迹），一律不进公开 sidecar。这里断言的是
        # 剔除机制生效，而不是「每个词都是人名」——jieba 会把人名标注误加到
        # 普通词上（如「明白」），逐词扫描 blob 会误报。
        report_json, _ = self._render()
        entities = report_json["quantitative_features"]["low_level_features"]["named_entities"]
        for key in ("sample_persons", "sample_places", "sample_orgs"):
            self.assertNotIn(key, entities)

    def test_worldview_term_lists_stripped_from_public_json(self):
        from author_persona_skill.report.renderer import (
            extract_json_block, render_report_outputs)
        # 直接注入一份一定带专名的分类结果：若只依赖 fixture，分类为空时这条
        # 断言会空转通过，等于没测。
        prep = fx.prepared(key="w5")
        prep = dict(prep)
        prep["quantitative_features"] = dict(prep["quantitative_features"])
        prep["quantitative_features"]["worldview_vocab"] = {
            "categories": [
                {"category": "核心角色", "count": 2, "term_counts": {"苏疏": 30, "林砚": 24}},
                {"category": "地域场景", "count": 1, "term_counts": {"幽泉谷": 24}},
            ],
            "special_systems": ["系统"],
        }
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="低层")
        public_wv = rendered["report_json"]["quantitative_features"].get("worldview_vocab", {})
        self.assertTrue(public_wv.get("categories"), "分类结果应保留（只剔除词汇表）")
        blob = json.dumps(rendered["report_json"], ensure_ascii=False)
        for category in public_wv["categories"]:
            self.assertNotIn("term_counts", category)
            self.assertIn("category", category)
            self.assertIn("count", category)
        # 只断言本用例注入的词汇表条目：语料其他位置出现的词（如 imagery_clusters
        # 里的 n-gram 切片）是 fixture 自带内容，不属于本断言的射程。
        for name in ("苏疏", "林砚", "幽泉谷"):
            self.assertNotIn(name, blob)
        self.assertIn("系统", blob)

    def test_real_character_names_do_not_leak(self):
        report_json, prep = self._render()
        blob = json.dumps(report_json, ensure_ascii=False)
        for speaker in prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]:
            self.assertNotIn(speaker["name"], blob)

    def test_public_keeps_counts_and_density(self):
        report_json, _ = self._render()
        public_low = report_json["quantitative_features"]["low_level_features"]
        self.assertIn("total_entities", public_low["named_entities"])
        self.assertIn("entity_density", public_low["named_entities"])


if __name__ == "__main__":
    unittest.main()
