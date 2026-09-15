# -*- coding: utf-8 -*-
"""Quantitative style analyzer.

Returns 15 blocks: text_summary / sentence_structure / paragraph_rhythm /
dialogue_features / punctuation_density / punctuation_ratios / rhetoric_features /
perspective_and_narration / description_density / imagery_clusters /
style_markers / knowledge_layer / low_level_features / worldview_vocab /
semantic_dimensions (plus the dialogue-embedded voiceprint data). Low-level
measurement (readability, TTR, hapax, clause complexity, sentiment, word length,
POS, entities, worldview) lives in ``analyzers/low_level.py``; the
correlation/DNA knowledge menu lives in ``analyzers/knowledge.py``.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from .noise import filter_noise
from .dialogue_analyzer import DialogueAnalyzer
from .rhetoric import count_similes
from .knowledge import build_knowledge_layer
from .low_level import analyze_low_level_with_worldview, sent_len_bracket as sent_len_bracket_label
from .cross_era import build_semantic_dimensions


def compute_median(numbers: List[float]) -> float:
    if not numbers:
        return 0.0
    sorted_nums = sorted(numbers)
    n = len(sorted_nums)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_nums[mid])
    return (sorted_nums[mid - 1] + sorted_nums[mid]) / 2.0


class StyleAnalyzer:
    """Computes comprehensive quantitative features from novel text."""

    def __init__(self):
        self.dialogue_analyzer = DialogueAnalyzer()

    def analyze(
        self,
        raw_text: str,
        chapters_meta: Optional[List[Dict[str, Any]]] = None,
        pre_cleaned: bool = False,
    ) -> Dict[str, Any]:
        """
        Run full quantitative analysis on text. Noise is filtered first so stats
        are clean, unless ``pre_cleaned`` is set -- the pipeline already filters
        the whole corpus once before sampling, and filtering twice would double-
        count noise statistics.
        """
        if pre_cleaned:
            clean_text = raw_text
            noise_ratio, noise_stats = 0.0, {"noise_ratio": 0.0, "noise_ratio_pct": "0.00%"}
        else:
            clean_text, noise_ratio, noise_stats = filter_noise(raw_text)
        total_chars = len(clean_text)
        if total_chars == 0:
            return self._empty_result(noise_stats)

        # 1. Paragraph analysis
        raw_paragraphs = clean_text.splitlines()
        paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
        total_paragraphs = max(len(paragraphs), 1)
        para_lens = [len(p) for p in paragraphs]
        avg_para_len = round(sum(para_lens) / total_paragraphs, 1)
        short_paras = [p for p in paragraphs if len(p) <= 8]
        short_para_ratio = round(len(short_paras) / total_paragraphs, 4)

        # Scene switching density: count scene switch cues (e.g. "数日后", "次日", "转眼", "与此同时", or divider breaks)
        scene_cue_patterns = [
            r'(?:次日|数日后|数月后|翌日|清晨|深夜|午后|傍晚|与此同时|同一时间|另一边|转眼间|不知不觉|时光飞逝)',
            r'(?:回到|来到|走进|离开|跨入|步入|行至|遁入|出现在)',
        ]
        scene_cues = 0
        for pat in scene_cue_patterns:
            scene_cues += len(re.findall(pat, clean_text))
        scene_switch_density = round((scene_cues / max(total_chars, 1)) * 1000, 2)

        # 2. Sentence analysis
        sentence_delimiters = re.compile(r'[。！？\n]')
        raw_sentences = sentence_delimiters.split(clean_text)
        sentences = [s.strip() for s in raw_sentences if s.strip()]
        total_sentences = max(len(sentences), 1)
        sentence_lens = [len(s) for s in sentences]
        avg_sent_len = round(sum(sentence_lens) / total_sentences, 1)
        median_sent_len = round(compute_median(sentence_lens), 1)

        short_sentences = [s for s in sentences if len(s) <= 10]
        long_sentences = [s for s in sentences if len(s) >= 50]
        short_sent_ratio = round(len(short_sentences) / total_sentences, 4)
        long_sent_ratio = round(len(long_sentences) / total_sentences, 4)

        sent_len_bracket = sent_len_bracket_label(avg_sent_len)

        # 3. Punctuation stats (per 1000 chars).
        # Units are punctuation *occurrences*: "……" and "——" each count once,
        # ASCII "." / "-" are excluded to avoid decimals & hyphens inflating counts.
        k_factor = 1000.0 / max(total_chars, 1)
        punc_counts = {
            "comma": len(re.findall(r"[，,]", clean_text)),
            "period": len(re.findall(r"。", clean_text)),
            "exclamation": len(re.findall(r"[！!]", clean_text)),
            "question": len(re.findall(r"[？?]", clean_text)),
            "ellipsis": len(re.findall(r"…+|\.{3,}", clean_text)),
            "colon": len(re.findall(r"[：:]", clean_text)),
            "dash": len(re.findall(r"—+|--+", clean_text)),
        }
        punc_density = {k: round(v * k_factor, 2) for k, v in punc_counts.items()}
        comma_period_ratio = round(punc_counts["comma"] / max(punc_counts["period"], 1), 2)
        excl_quest_sum = round((punc_counts["exclamation"] + punc_counts["question"]) * k_factor, 2)

        # 4. Rhetoric analysis (simile unit: sentences carrying explicit markers)
        metaphor_count = count_similes(clean_text)
        metaphor_density = round(metaphor_count * k_factor, 2)

        rhetorical_q_count = len(re.findall(r'(?:难道|岂|莫非|何必|何曾|怎能|何尝)[\u4e00-\u9fa5]{1,25}[？?]', clean_text))
        rhetorical_q_density = round(rhetorical_q_count * k_factor, 2)

        parallelism_count = len(re.findall(r'((?:[\u4e00-\u9fa5]{2,6}[，、]){2,}[\u4e00-\u9fa5]{2,6}[。！？])', clean_text))
        parallelism_density = round(parallelism_count * k_factor, 2)

        # 5. Narrative point of view & pronouns.
        # Exclude compound words (其他/它们 inside 其它 etc.) before counting,
        # so single-char substrings don't inflate counts.
        pov_text = clean_text.replace("其他", "").replace("其它", "")
        third_p_count = sum(pov_text.count(p) for p in ("他", "她", "它"))
        first_p_count = sum(pov_text.count(p) for p in ("我", "俺", "咱", "在下", "老子"))
        pov_tendency = "第三人称全知/限知" if third_p_count >= first_p_count * 2 else ("第一人称" if first_p_count > third_p_count else "混合视角")

        # 6. Description density (Action vs Mental vs Environment).
        # Unit: sentences classified by dominant category — single-char keyword
        # substring counting inflated env/action counts via words like 火光/进入.
        action_verbs = [
            "走", "跑", "跳", "冲", "杀", "斩", "拔", "握", "拍", "击", "退", "进", "闪", "跨",
            "劈", "砸", "刺", "踏", "抓", "挥", "甩", "跃", "撕", "咬", "探", "震", "掠", "飞",
            "拿", "放", "站", "坐", "推", "拉", "拖", "抱", "跪", "爬", "举", "压", "踢", "挡",
            "点头", "摇头", "转身", "回头", "伸手", "抬头", "低头", "起身",
        ]
        mental_verbs = [
            "想", "思索", "暗想", "心想", "暗道", "回忆", "琢磨", "沉思", "惊疑", "犹疑", "盘算",
            "察觉", "感受", "领会", "明白", "恍然", "不解", "暗忖", "料定", "震惊", "骇然",
            "觉得", "认为", "猜到", "疑惑", "迟疑", "犹豫", "心念", "暗自", "寻思",
        ]
        env_words = [
            "风", "雨", "雷", "云", "雾", "光", "影", "山", "水", "林", "石", "树", "月", "日",
            "星", "夜", "殿", "阁", "峰", "海", "江", "河", "天", "地", "寒", "热", "冷", "暖",
        ]

        action_count = 0
        mental_count = 0
        env_count = 0
        for sent in sentences:
            a = sum(sent.count(v) for v in action_verbs)
            m = sum(sent.count(v) for v in mental_verbs)
            # Env single-char words (天/地/光/水...) appear inside countless
            # idioms; require a strict lead of ≥2 hits to classify as env.
            e = sum(sent.count(v) for v in env_words)
            if e > max(a, m) and e >= 2:
                env_count += 1
                continue
            best = max(a, m, e)
            if best == 0:
                continue
            if a >= m and a >= e:
                action_count += 1
            elif m >= e:
                mental_count += 1
            else:
                env_count += 1

        action_mental_ratio = round(action_count / max(mental_count, 1), 2)
        driver_mode = "强动作/事件驱动" if action_mental_ratio >= 3.0 else ("平衡驱动" if action_mental_ratio >= 1.2 else "内心/意识流驱动")

        # 7. Dialogue analysis
        dialogue_data = self.dialogue_analyzer.extract_dialogues(clean_text, chapters_meta)

        # 8. High-frequency content-word clusters (adaptive, not a fixed genre lexicon).
        # Threshold scales with corpus size so n=3 noise can never surface.
        _FUNC_CHARS = set("的了吗是在有和就个也这那都很到上过得着不为他她它说我你它们个之其把被向从对于")
        _STOPWORDS = {
            "一个", "什么", "自己", "没有", "这个", "那个", "知道", "现在", "起来", "下来",
            "出来", "时候", "已经", "不是", "就是", "还是", "一下", "一声", "有些", "一点",
            "这么", "那么", "怎么", "如果", "因为", "但是", "不过", "可以", "不能", "不会",
            "东西", "地方", "问题", "事情", "样子", "声音", "目光", "身体", "脸上", "心中",
        }
        # Character names are not imagery. Without this filter the most frequent
        # speakers dominated the cluster list and leaked identities into the
        # public sidecar (the mapping only covers candidates, and only the top
        # speakers are candidates).
        _speaker_names = {
            str(speaker.get("name", "")).strip()
            for speaker in dialogue_data.get("high_confidence_speakers", [])
            if str(speaker.get("name", "")).strip()
        } | {
            str(name).strip() for name in dialogue_data.get("low_confidence_candidates", [])
            if str(name).strip()
        }
        _speaker_names = {name for name in _speaker_names if len(name) >= 2}

        def _is_name_like(word: str) -> bool:
            return any(name in word or word in name for name in _speaker_names)

        word_freq: Counter[str] = Counter(re.findall(r"[\u4e00-\u9fa5]{2,3}", clean_text))
        min_freq = max(10, int(total_chars / 7000))
        # Overlap suppression: sliding n-grams over a repeated phrase produce
        # near-duplicate entries ("石屑簌" / "簌落下" / "屑簌落"). Once a word is
        # selected, positions it already covers no longer justify a new entry.
        covered = bytearray(len(clean_text))
        imagery_counts: Dict[str, int] = {}
        for word, freq in word_freq.most_common(400):
            if freq < min_freq or len(imagery_counts) >= 8:
                break
            if word in _STOPWORDS or any(c in _FUNC_CHARS for c in word):
                continue
            if _is_name_like(word):
                continue
            positions = [m.start() for m in re.finditer(re.escape(word), clean_text)]
            if positions and sum(covered[p] for p in positions) / len(positions) > 0.7:
                continue
            for start in positions:
                covered[start:start + len(word)] = b"\x01" * len(word)
            imagery_counts[word] = freq

        # 9. Style markers — neutral numeric signals only (no literary verdicts,
        # which would pre-bias the LLM's interpretation).
        style_markers = []
        if short_sent_ratio >= 0.30:
            style_markers.append(f"短句率 {short_sent_ratio * 100:.1f}%（超过30%参考线）")
        if dialogue_data["dialogue_ratio"] >= 0.30:
            style_markers.append(f"对话字符占比 {dialogue_data['dialogue_ratio_pct']}（超过30%参考线）")
        if metaphor_density >= 2.0:
            style_markers.append(f"比喻句密度 {metaphor_density}/千字")
        if punc_density["dash"] >= 1.5:
            style_markers.append(f"破折号 {punc_density['dash']}次/千字（高频出现）")
        if punc_density["ellipsis"] >= 1.5:
            style_markers.append(f"省略号 {punc_density['ellipsis']}次/千字（高频出现）")
        if avg_sent_len >= 28:
            style_markers.append(f"平均句长 {avg_sent_len} 字（偏长区间）")
        if action_mental_ratio >= 2.5:
            style_markers.append(f"动作:心理比 {action_mental_ratio}（动作主导句显著偏多）")
        if not style_markers:
            style_markers.append(f"各项指标处于常规区间（平均句长 {avg_sent_len} 字，对话占比 {dialogue_data['dialogue_ratio_pct']}）")

        result = {
            "text_summary": {
                "total_chars": total_chars,
                "total_paragraphs": total_paragraphs,
                "total_sentences": total_sentences,
                "noise_ratio": noise_stats["noise_ratio"],
                "noise_ratio_pct": noise_stats["noise_ratio_pct"],
                "noise_stats": noise_stats,
            },
            "sentence_structure": {
                "avg_sent_len": avg_sent_len,
                "median_sent_len": median_sent_len,
                "short_sent_ratio": short_sent_ratio,
                "short_sent_ratio_pct": f"{short_sent_ratio * 100:.1f}%",
                "long_sent_ratio": long_sent_ratio,
                "long_sent_ratio_pct": f"{long_sent_ratio * 100:.1f}%",
                "sent_len_bracket": sent_len_bracket,
            },
            "paragraph_rhythm": {
                "avg_para_len": avg_para_len,
                "short_para_ratio": short_para_ratio,
                "short_para_ratio_pct": f"{short_para_ratio * 100:.1f}%",
                "scene_switch_density": scene_switch_density,
            },
            "dialogue_features": dialogue_data,
            "punctuation_density": punc_density,
            "punctuation_ratios": {
                "comma_period_ratio": comma_period_ratio,
                "exclamation_question_density": excl_quest_sum,
            },
            "rhetoric_features": {
                "metaphor_density": metaphor_density,
                "rhetorical_question_density": rhetorical_q_density,
                "parallelism_density": parallelism_density,
            },
            "perspective_and_narration": {
                "pov_tendency": pov_tendency,
                "third_person_count": third_p_count,
                "first_person_count": first_p_count,
            },
            "description_density": {
                "unit": "sentences",
                "action_count": action_count,
                "mental_count": mental_count,
                "env_count": env_count,
                "action_mental_ratio": action_mental_ratio,
                "driver_mode": driver_mode,
            },
            "imagery_clusters": dict(sorted(imagery_counts.items(), key=lambda x: x[1], reverse=True)[:8]),
            "style_markers": style_markers[:5],
        }
        # 知识层：维度间关联信号、风格 DNA 候选、通用禁用词。全部标注非权威，
        # 只是喂给分析提示词的候选菜单（见 analyzers/knowledge.py 的说明）。
        result["knowledge_layer"] = build_knowledge_layer(result)
        # 低层测量层：可读性四式 / TTR / hapax / 分句复杂度 / 情感 / 词长 / 词性 /
        # 实体 / 世界观五类。两块共享同一次分词，缺失分词器时整块标注 degraded。
        result["low_level_features"], result["worldview_vocab"] = (
            analyze_low_level_with_worldview(clean_text))
        # 语义子维度：对话功能分布复用 dialogue_features 已算好的实测值（原始引语
        # 只在 dialogue_analyzer 内可见），POV 稳定性在此补。
        result["semantic_dimensions"] = build_semantic_dimensions(
            clean_text, dialogue_functions=dialogue_data.get("dialogue_functions"))
        return result

    def _empty_result(self, noise_stats: Dict[str, Any]) -> Dict[str, Any]:
        """Shape-compatible empty result so callers never branch on missing keys."""
        return {
            "text_summary": {
                "total_chars": 0, "total_paragraphs": 0, "total_sentences": 0,
                "noise_ratio": 0.0, "noise_ratio_pct": noise_stats.get("noise_ratio_pct", "0.00%"),
                "noise_stats": noise_stats,
            },
            "sentence_structure": {"avg_sent_len": 0, "median_sent_len": 0, "short_sent_ratio": 0, "long_sent_ratio": 0, "sent_len_bracket": "无数据"},
            "paragraph_rhythm": {"avg_para_len": 0, "short_para_ratio": 0, "scene_switch_density": 0},
            "dialogue_features": {"total_quotes": 0, "dialogue_chars": 0, "dialogue_ratio": 0, "dialogue_ratio_pct": "0.00%", "tag_frequencies": {}, "dao_shuo_ratio": 0, "high_confidence_speakers": [], "low_confidence_candidates": []},
            "punctuation_density": {},
            "punctuation_ratios": {},
            "rhetoric_features": {},
            "perspective_and_narration": {},
            "description_density": {},
            "imagery_clusters": {},
            "style_markers": [],
        }
