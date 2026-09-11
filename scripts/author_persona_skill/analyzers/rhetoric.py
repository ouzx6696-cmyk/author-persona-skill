# -*- coding: utf-8 -*-
"""Shared rhetoric detectors: explicit simile/metaphor sentence matching.

Single source of truth for both style_analyzer (density metrics) and
evidence anchor extraction, so density numbers and cited examples always
come from the same detector.
"""
from __future__ import annotations

import re
from typing import List

# Strong simile markers: multi-character, virtually never used in non-figurative sense.
_STRONG_MARKERS = (
    "宛如", "宛若", "犹如", "如同", "恰似", "恍若", "恍如", "仿若",
    "好似", "就像", "像是", "仿佛", "恰如", "浑如", "似的",
)

# 如一 的成语尾巴（始终如一/一如既往/一如往日/十年如一日…）不是比喻，但
# "如一 + 量词"（如一柄长刀/如一道闪电）是真比喻。校准记录：旧规则把 一
# 整类排除，漏计了这类句子；比喻密度是核心审计指标，漏计会同时压低报告
# 数值与证据可选范围，而裸"像"规则本无此限制（像一道闪电可命中）。
_RU_IDIOM_TAIL = (
    r"(?:一(?:[^\u4e00-\u9fa5]|$|[日贯体味致般律成])"
    r"|既往|往日|往前|往昔|往常|从(?:前|来))"
)

# Bare "如" counts only when followed by a nominal phrase, excluding the
# grammaticalized usages (如果/如何/如此/例如/不如/如下...) and the
# exemplification collocations (比如说/比如说着/如说).
_BARE_RU_RE = re.compile(
    r"(?<![不譬例诸无比])如"
    r"(?![果何是此例下上前今后今同实愿期次许旧常初二了着过说])"
    r"(?!" + _RU_IDIOM_TAIL + r")"
    r"(?=[一这那每]{0,2}[\u4e00-\u9fa5]{1,12})"
)

# Bare "像" only counts when followed by a nominal phrase and not preceded by
# characters that form non-figurative words (好像 is handled above; here we guard
# 不像/图像/摄像/录像/影像/画像/偶像 etc.).
_BARE_XIANG_RE = re.compile(r"(?<![不好图摄录影偶神活])像(?=[一这那每]{0,2}[\u4e00-\u9fa5]{1,12})")

_SENT_SPLIT = re.compile(r"[。！？\n]")

# Sentences that merely mention markers inside questions/negations about likeness.
_NEGATION_GUARD = re.compile(r"(?:不像|哪里像|怎么像|谁像)")


def is_simile_sentence(sentence: str) -> bool:
    """Return True when a sentence contains an explicit simile construction."""
    if _NEGATION_GUARD.search(sentence):
        # Strip negated fragments before judging the remainder.
        sentence = _NEGATION_GUARD.sub("", sentence)
    for marker in _STRONG_MARKERS:
        if marker in sentence:
            return True
    if _BARE_RU_RE.search(sentence):
        return True
    if _BARE_XIANG_RE.search(sentence):
        return True
    return False


def find_simile_sentences(text: str, min_len: int = 8, max_len: int = 80) -> List[str]:
    """Extract clean sentences containing explicit similes."""
    results: List[str] = []
    for raw in _SENT_SPLIT.split(text):
        s = raw.strip().strip("，、；：")
        if not (min_len <= len(s) <= max_len):
            continue
        if is_simile_sentence(s):
            results.append(s)
    return results


def count_similes(text: str) -> int:
    """Count simile-bearing sentences (unit: sentences, not substring hits).

    Uses the same min_len=8 window as the evidence anchors
    (distill/evidence.py), so the reported metaphor density and the
    selectable evidence quotes share one measurement basis.
    """
    return len(find_simile_sentences(text))
