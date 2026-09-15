# -*- coding: utf-8 -*-
"""知识层：维度间关联规则、风格 DNA 候选、通用 AI 味禁用词。

归档版 v7.0.0 把这三样硬编码在 `formatter.py` / `builder.py` /
`prompt_templates.py` 里，迭代中整体丢失。恢复时做了两处形态调整以适配现有设计：

1. **候选而非结论**。旧版 `build_style_dna_label` 返回单一标签（`max(scores)`），
   等于用阈值表替分析器下文学判断——与本技能「分析器只测量、不下结论」冲突。
   这里改为输出**降序候选列表**，允许同为 0 分、允许无候选，并在返回值里显式
   标注 `authoritative: False`；判决权交回 LLM 与用户。
2. **缺数据即跳过**。部分规则需要 TTR / 功能词占比（由低层测量层提供）。这些
   规则在字段缺失时自动不产信号，等低层测量接入后自行激活——不需要再改这里。

三者同时作为**提示词知识菜单**注入（见 `report/templates.py`）：措辞为「以下为
候选解读，须由本次实测数值落地后才可采用」。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 通用 AI 味禁用词（10 条，归档 GENERIC_TABOO_PHRASES 原样）
# ---------------------------------------------------------------------------
GENERIC_TABOO_PHRASES: Tuple[str, ...] = (
    "总而言之", "综上所述", "值得注意的是", "由此可见",
    "也就是说", "我们可以看到", "从这个角度来看",
    "需要指出的是", "值得一提的是", "必须承认的是",
)


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_to_float(value: Any) -> Optional[float]:
    """Accept both '34.0%' and 0.34 / 34 forms; return a 0–100 number."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip().rstrip("%")
        out = _num(text)
    else:
        out = _num(value)
    if out is None:
        return None
    if out <= 1.0:
        out *= 100.0
    return out


class _Metrics:
    """Flat, missing-tolerant view over quantitative_features.

    Rules read named metrics here instead of reaching into nested dicts, so a
    renaming or a not-yet-implemented metric degrades to ``None`` (rule skipped)
    rather than raising.
    """

    def __init__(self, quant: Dict[str, Any]):
        quant = quant or {}
        sent = quant.get("sentence_structure", {}) or {}
        para = quant.get("paragraph_rhythm", {}) or {}
        dlg = quant.get("dialogue_features", {}) or {}
        punc = quant.get("punctuation_density", {}) or {}
        rh = quant.get("rhetoric_features", {}) or {}
        desc = quant.get("description_density", {}) or {}
        vocab = quant.get("vocabulary_richness", {}) or {}
        low = quant.get("low_level_features", {}) or {}
        sentiment = low.get("sentiment", {}) or quant.get("sentiment", {}) or {}

        self.short_rate = (
            _pct_to_float(sent.get("short_sent_ratio_pct"))
            if sent.get("short_sent_ratio_pct") is not None
            else _pct_to_float(sent.get("short_sent_ratio"))
        )
        self.long_rate = (
            _pct_to_float(sent.get("long_sent_ratio_pct"))
            if sent.get("long_sent_ratio_pct") is not None
            else _pct_to_float(sent.get("long_sent_ratio"))
        )
        self.avg_len = _num(sent.get("avg_sent_len"))
        self.short_para_rate = (
            _pct_to_float(para.get("short_para_ratio_pct"))
            if para.get("short_para_ratio_pct") is not None
            else _pct_to_float(para.get("short_para_ratio"))
        )

        self.exclaim_d = _num(punc.get("exclamation"))
        self.question_d = _num(punc.get("question"))
        self.ellipsis_d = _num(punc.get("ellipsis"))
        self.dash_d = _num(punc.get("dash"))
        self.metaphor_d = _num(rh.get("metaphor_density"))

        self.dialogue_count = _num(dlg.get("total_quotes"))
        dialogue_ratio = _num(dlg.get("dialogue_ratio"))
        if dialogue_ratio is not None:
            self.d_n_ratio: Optional[float] = dialogue_ratio / max(1e-6, 1.0 - dialogue_ratio)
        else:
            self.d_n_ratio = _num(dlg.get("dialogue_narrative_ratio"))

        action = _num(desc.get("action_count"))
        mental = _num(desc.get("mental_count"))
        env = _num(desc.get("env_count"))
        total = sum(v for v in (action, mental, env) if v is not None)
        self.total_desc = total
        self.action_pct = (action / total * 100.0) if total and action is not None else None
        self.psych_pct = (mental / total * 100.0) if total and mental is not None else None
        self.env_pct = (env / total * 100.0) if total and env is not None else None

        # Vocabulary metrics arrive with the low-level measurement layer; absent
        # until then, which simply disables the two rules that need them.
        self.ttr = _num(vocab.get("ttr")) if vocab else None
        self.ttr_filtered = _num(vocab.get("ttr_filtered")) if vocab else None
        self.func_ratio = _num(vocab.get("function_word_ratio")) if vocab else None
        self.balance = _num(sentiment.get("sentiment_balance"))


# ---------------------------------------------------------------------------
# 维度间关联规则（8 条）
# ---------------------------------------------------------------------------
#: Each rule: (id, required metric names, predicate, signal text).
#: A rule whose required metrics are unavailable emits nothing.
CROSS_METRIC_RULES: Tuple[Tuple[str, Tuple[str, ...], Callable[[_Metrics], bool], str], ...] = (
    ("X1", ("short_rate", "exclaim_d"),
     lambda m: m.short_rate > 30 and m.exclaim_d > 5,
     "短句多 + 感叹号多 → 情绪外放型写作，节奏急促、表达直接"),
    ("X2", ("short_rate", "exclaim_d"),
     lambda m: m.short_rate > 30 and m.exclaim_d < 2,
     "短句多 + 感叹号少 → 冷静快节奏型，用短句制造速度而非情绪"),
    ("X3", ("short_para_rate", "dialogue_count"),
     lambda m: m.short_para_rate > 20 and (m.dialogue_count or 0) > 0,
     "极短段落多 + 对话多 → 对话驱动、视觉节奏强，典型的网文快节奏"),
    ("X4", ("ttr", "metaphor_d"),
     lambda m: m.ttr is not None and m.ttr > 0.5 and (m.metaphor_d or 0) > 3,
     "词汇丰富 + 比喻多 → 文学性较强，善用意象与修辞"),
    ("X5", ("ttr", "func_ratio"),
     lambda m: m.ttr is not None and m.ttr < 0.35 and (m.func_ratio or 0) > 0.35,
     "词汇重复度高 + 功能词多 → 口语化风格，核心词高频复用"),
    ("X6", ("total_desc", "psych_pct", "exclaim_d"),
     lambda m: m.total_desc > 0 and (m.psych_pct or 0) > 30 and (m.exclaim_d or 0) < 3,
     "心理描写多 + 感叹号少 → 内省型写作，情绪表达含蓄内敛"),
    ("X7", ("total_desc", "action_pct", "short_rate"),
     lambda m: m.total_desc > 0 and (m.action_pct or 0) > 50 and (m.short_rate or 0) > 25,
     "动作描写主导 + 短句多 → 动作驱动快节奏，画面感强"),
    ("X8", ("total_desc", "env_pct", "avg_len"),
     lambda m: m.total_desc > 0 and (m.env_pct or 0) > 25 and (m.avg_len or 0) > 30,
     "环境描写多 + 长句偏多 → 氛围营造型，善于铺陈场景"),
)

#: Metric names a rule needs, resolved against the analyzer's actual keys.
_METRIC_ALIASES: Dict[str, str] = {
    "short_rate": "short_sent_ratio_pct",
    "long_rate": "long_sent_ratio_pct",
    "avg_len": "avg_sent_len",
    "short_para_rate": "short_para_ratio_pct",
    "exclaim_d": "punc_exclamation",
    "question_d": "punc_question",
    "ellipsis_d": "punc_ellipsis",
    "dash_d": "punc_dash",
    "metaphor_d": "metaphor_density",
    "dialogue_count": "total_quotes",
    "d_n_ratio": "dialogue_ratio",
    "action_pct": "action_pct",
    "psych_pct": "psych_pct",
    "env_pct": "env_pct",
    "total_desc": "description_density",
    "ttr": "ttr",
    "ttr_filtered": "ttr_filtered",
    "func_ratio": "function_word_ratio",
    "balance": "sentiment_balance",
}


def evaluate_cross_metric_rules(quant: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Evaluate the 8 correlation rules; missing inputs skip silently."""
    metrics = _Metrics(quant)
    signals: List[Dict[str, Any]] = []
    for rule_id, required, predicate, text in CROSS_METRIC_RULES:
        if any(getattr(metrics, name, None) is None for name in required):
            continue
        try:
            hit = bool(predicate(metrics))
        except (TypeError, ZeroDivisionError):
            continue
        if not hit:
            continue
        signals.append({
            "rule_id": rule_id,
            "signal": text,
            "basis": {_METRIC_ALIASES.get(name, name): getattr(metrics, name) for name in required},
            "authoritative": False,
        })
    return signals


# ---------------------------------------------------------------------------
# 风格 DNA 候选（13 类 + 3 兜底）
# ---------------------------------------------------------------------------
#: (label, required metric names, gate predicate, score function)
#: Gate and score are separate so a label with a real score never comes from a
#: degenerate input (e.g. a missing exclamation density read as 0).
DNA_CANDIDATES: Tuple[Tuple[str, Tuple[str, ...], Callable[[_Metrics], bool], Callable[[_Metrics], float]], ...] = (
    ("轻松搞笑型", ("short_rate", "exclaim_d"),
     lambda m: m.short_rate > 35 and m.exclaim_d > 5,
     lambda m: m.short_rate * 0.3 + m.exclaim_d * 2),
    ("冷静快节奏型", ("short_rate", "exclaim_d"),
     lambda m: m.short_rate > 30 and m.exclaim_d < 2,
     lambda m: m.short_rate * 0.3 + (2 - m.exclaim_d) * 3),
    ("推理驱动型", ("question_d", "exclaim_d"),
     lambda m: m.question_d > 5 and m.exclaim_d < m.question_d * 0.5,
     lambda m: m.question_d * 2 + (m.question_d - m.exclaim_d) * 0.5),
    ("对话驱动型", ("short_rate", "d_n_ratio"),
     lambda m: m.short_rate > 25 and m.d_n_ratio > 0.8,
     lambda m: m.short_rate * 0.2 + m.d_n_ratio * 10),
    ("动作快节奏型", ("action_pct", "short_rate"),
     lambda m: (m.action_pct or 0) > 60 and m.short_rate > 20,
     lambda m: m.action_pct * 0.3 + m.short_rate * 0.2),
    ("内省克制型", ("psych_pct", "exclaim_d"),
     lambda m: (m.psych_pct or 0) > 35 and (m.exclaim_d or 0) < 3,
     lambda m: m.psych_pct * 0.3 + (3 - (m.exclaim_d or 0)) * 2),
    ("铺陈留白型", ("avg_len", "ellipsis_d"),
     lambda m: m.avg_len > 35 and (m.ellipsis_d or 0) > 2,
     lambda m: m.avg_len * 0.2 + (m.ellipsis_d or 0) * 2),
    ("热血爆发型", ("exclaim_d", "short_rate"),
     lambda m: m.exclaim_d > 8 and m.short_rate > 25,
     lambda m: m.exclaim_d * 2 + m.short_rate * 0.2),
    ("暗黑深沉型", ("balance", "psych_pct"),
     lambda m: m.balance is not None and m.balance < -0.3 and (m.psych_pct or 0) > 25,
     lambda m: abs(m.balance) * 10 + (m.psych_pct or 0) * 0.2),
    ("极简利落型", ("avg_len", "short_rate"),
     lambda m: m.avg_len < 20 and m.short_rate > 35,
     lambda m: (20 - m.avg_len) * 0.5 + m.short_rate * 0.3),
    ("克制写实型", ("ellipsis_d", "exclaim_d"),
     lambda m: (m.ellipsis_d or 0) < 0.3 and (m.exclaim_d or 0) < 2,
     lambda m: (0.3 - (m.ellipsis_d or 0)) * 10 + (2 - (m.exclaim_d or 0)) * 2),
    ("热血爽文型", ("exclaim_d", "balance"),
     lambda m: m.exclaim_d > 5 and m.balance is not None and m.balance > 0.2,
     lambda m: m.exclaim_d * 1.5 + m.balance * 10),
    ("悬疑动作型", ("question_d", "action_pct"),
     lambda m: m.question_d > 3 and (m.action_pct or 0) > 50,
     lambda m: m.question_d * 2 + m.action_pct * 0.1),
)

#: 兜底候选：阈值表全不命中时给出方向性描述，优先级低于任何命中项。
DNA_FALLBACKS: Tuple[Tuple[str, Callable[[_Metrics], bool]], ...] = (
    ("快节奏叙事型", lambda m: (m.short_rate or 0) > 25),
    ("沉稳铺陈型", lambda m: (m.avg_len or 0) > 30),
    ("均衡叙事型", lambda m: True),
)


def build_style_dna_candidates(quant: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return scored style-DNA candidates, descending.

    Unlike the archive's single-label return, every gated label with a positive
    score is kept: the caller (LLM / user) decides, and ties remain visible.
    Marked ``authoritative: False`` — this is a derived prompt hint, not a
    verdict about the writer.
    """
    metrics = _Metrics(quant)
    scored: List[Tuple[str, float]] = []
    for label, required, gate, score in DNA_CANDIDATES:
        if any(getattr(metrics, name, None) is None for name in required):
            continue
        try:
            if not gate(metrics):
                continue
            value = float(score(metrics))
        except (TypeError, ZeroDivisionError):
            continue
        if value <= 0:
            continue
        scored.append((label, round(value, 2)))

    if not scored:
        for label, gate in DNA_FALLBACKS:
            try:
                if gate(metrics):
                    scored.append((label, 0.0))
                    break
            except (TypeError, ZeroDivisionError):
                continue

    # Descending by score; ties broken by label so output is deterministic.
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [
        {"label": label, "score": value, "authoritative": False}
        for label, value in scored[:5]
    ]


def build_knowledge_layer(quant: Dict[str, Any]) -> Dict[str, Any]:
    """The full knowledge-layer block folded into quantitative_features."""
    return {
        "cross_metric_signals": evaluate_cross_metric_rules(quant),
        "style_dna_candidates": build_style_dna_candidates(quant),
        "generic_taboo_phrases": list(GENERIC_TABOO_PHRASES),
    }
