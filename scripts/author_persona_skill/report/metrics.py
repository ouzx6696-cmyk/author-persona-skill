# -*- coding: utf-8 -*-
"""Numeric fidelity layer for the quantitative report section.

Three cooperating mechanisms:
1. build_placeholder_map  — turns measured values into {{token}} registry.
2. substitute_placeholders — replaces tokens in LLM prose so every reported
   number physically originates from prepare-stage measurement.
3. audit_numeric_claims   — reverse check: any bare number written next to a
   metric keyword must match the measured value within tolerance.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Metric Registry: MID is the machine key, {{token}} stays as alias.
# Every metric carries scope/formula/version so full_corpus vs sample scopes
# can never be confused (total_chars uses sample scope, noise uses
# whole-book scope).
# ---------------------------------------------------------------------------
METRIC_VERSION = "4"

# (mid, placeholder_token, unit, scope, formula)
METRIC_DEFS: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("M001", "total_chars", "chars", "sample", "len(sample_text)"),
    ("M002", "total_paragraphs", "count", "sample", "non-empty lines"),
    ("M003", "total_sentences", "count", "sample", "split on 。！？\\n"),
    ("M004", "noise_ratio_pct", "%", "full_corpus", "noise_chars/full_chars"),
    ("M010", "avg_sent_len", "chars", "sample", "sum(sent_len)/n_sent"),
    ("M011", "median_sent_len", "chars", "sample", "median(sent_len)"),
    ("M012", "short_sent_ratio_pct", "%", "sample", "len<=10/n_sent"),
    ("M013", "long_sent_ratio_pct", "%", "sample", "len>=50/n_sent"),
    ("M020", "avg_para_len", "chars", "sample", "sum(para_len)/n_para"),
    ("M021", "short_para_ratio_pct", "%", "sample", "len<=8/n_para"),
    ("M022", "scene_switch_density", "/kchars", "sample", "cues*1000/chars"),
    ("M030", "dialogue_ratio_pct", "%", "sample", "dialogue_chars/total"),
    ("M031", "dao_shuo_ratio", "ratio", "sample", "dao_tags/max(shuo,1)"),
    ("M040", "punc_comma", "/kchars", "sample", "count*1000/chars"),
    ("M041", "punc_period", "/kchars", "sample", "count*1000/chars"),
    ("M042", "punc_exclamation", "/kchars", "sample", "count*1000/chars"),
    ("M043", "punc_question", "/kchars", "sample", "count*1000/chars"),
    ("M044", "punc_ellipsis", "/kchars", "sample", "count*1000/chars"),
    ("M045", "punc_dash", "/kchars", "sample", "count*1000/chars"),
    ("M050", "comma_period_ratio", "ratio", "sample", "comma/max(period,1)"),
    ("M060", "metaphor_density", "/kchars", "sample", "simile_sents*1000/chars"),
    ("M061", "rhetorical_question_density", "/kchars", "sample", "rq*1000/chars"),
    ("M062", "parallelism_density", "/kchars", "sample", "parallel*1000/chars"),
    ("M070", "action_mental_ratio", "ratio", "sample", "action/max(mental,1)"),
    # 低层测量层（W5）。全部为启发式/分词依赖指标，进注册表供占位符与审计使用，
    # 但**不进 CORE_AUDIT_TOKENS** —— 核心 8 项保持稳定，避免下游预期漂移；这些
    # 新指标冲突只 warning（见 quality-baseline §4 的数据源可靠性分级）。
    ("M080", "readability_level", "label", "sample", "3-factor band"),
    ("M081", "gunning_fog_index", "index", "sample", "0.4*(words/sent+100*complex_ratio)"),
    ("M082", "yang_chengshu_index", "index", "sample", "0.4*(chars/sent+100*complex_ratio)"),
    ("M083", "flesch_kincaid_grade", "index", "sample", "0.39*chars/sent+11.8*chars/word-15.59"),
    ("M084", "smog_index", "index", "sample", "SMOG adapted"),
    ("M085", "complex_word_ratio", "ratio", "sample", "len>=4/n_words"),
    ("M090", "ttr", "ratio", "sample", "types/tokens"),
    ("M091", "ttr_filtered", "ratio", "sample", "types(2+)/tokens(2+)"),
    ("M092", "hapax_ratio", "ratio", "sample", "hapax/types"),
    ("M093", "avg_clauses_per_sentence", "count", "sample", "clauses/n_sent"),
    ("M094", "subordinate_ratio", "ratio", "sample", "subordinate/clauses"),
    ("M095", "coordinate_ratio", "ratio", "sample", "coordinate/clauses"),
    ("M096", "sentiment_balance", "ratio", "sample", "(pos-neg)/(pos+neg)"),
    ("M097", "entity_density", "ratio", "sample", "entities/tokens"),
    ("M098", "verb_ratio", "ratio", "sample", "verb/content_words"),
    ("M099", "adjective_ratio", "ratio", "sample", "adj/content_words"),
)

_TOKEN_TO_MID = {tok: mid for mid, tok, _u, _s, _f in METRIC_DEFS}
_MID_TO_TOKEN = {mid: tok for mid, tok, _u, _s, _f in METRIC_DEFS}


def build_metric_registry(quant: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build MID registry from quantitative_features. Values come from the
    same placeholder map so MID and {{token}} can never diverge."""
    ph = build_placeholder_map(quant)
    ts = quant.get("text_summary", {})
    denom = f"sample_chars={ts.get('total_chars', '?')}"
    reg: Dict[str, Dict[str, Any]] = {}
    for mid, tok, unit, scope, formula in METRIC_DEFS:
        if tok not in ph:
            continue
        reg[mid] = {
            "mid": mid,
            "token": tok,
            "name": tok,
            "value": ph[tok],
            "unit": unit,
            "scope": scope,
            "formula": formula,
            "denominator": denom if scope == "sample" else "full_corpus",
            "metric_version": METRIC_VERSION,
        }
    return reg


_METRIC_REF_RE = re.compile(r"\{\{\s*metric\s*:\s*([A-Za-z0-9_]+)\s*\}\}")


def substitute_metric_refs(text: str, registry: Dict[str, Dict[str, Any]]) -> str:
    """Replace {{metric:Mxxx}} (or {{metric:token}}) with measured values."""
    def repl(m: "re.Match[str]") -> str:
        key = m.group(1).strip()
        if key in registry:
            return str(registry[key].get("value", m.group(0)))
        # allow token form {{metric:avg_sent_len}}
        mid = _TOKEN_TO_MID.get(key)
        if mid and mid in registry:
            return str(registry[mid].get("value", m.group(0)))
        return m.group(0)
    return _METRIC_REF_RE.sub(repl, text)


def find_unresolved_metric_refs(text: str, registry: Dict[str, Dict[str, Any]]) -> List[str]:
    out = []
    for m in _METRIC_REF_RE.finditer(text):
        key = m.group(1).strip()
        if key not in registry and _TOKEN_TO_MID.get(key) not in registry:
            out.append(key)
    return sorted(set(out))

def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def build_placeholder_map(quant: Dict[str, Any]) -> Dict[str, str]:
    """Map {{token}} -> measured string value, from quantitative_features."""
    sent = quant.get("sentence_structure", {})
    para = quant.get("paragraph_rhythm", {})
    dlg = quant.get("dialogue_features", {})
    punc_d = quant.get("punctuation_density", {})
    punc_r = quant.get("punctuation_ratios", {})
    rh = quant.get("rhetoric_features", {})
    pov = quant.get("perspective_and_narration", {})
    desc = quant.get("description_density", {})
    ts = quant.get("text_summary", {})

    mapping = {
        "total_chars": _fmt(ts.get("total_chars", "")),
        "total_paragraphs": _fmt(ts.get("total_paragraphs", "")),
        "total_sentences": _fmt(ts.get("total_sentences", "")),
        "noise_ratio_pct": _fmt(ts.get("noise_ratio_pct", "0.00%")),
        "avg_sent_len": _fmt(sent.get("avg_sent_len", "")),
        "median_sent_len": _fmt(sent.get("median_sent_len", "")),
        "short_sent_ratio_pct": _fmt(sent.get("short_sent_ratio_pct", "")),
        "long_sent_ratio_pct": _fmt(sent.get("long_sent_ratio_pct", "")),
        "sent_len_bracket": _fmt(sent.get("sent_len_bracket", "")),
        "avg_para_len": _fmt(para.get("avg_para_len", "")),
        "short_para_ratio_pct": _fmt(para.get("short_para_ratio_pct", "")),
        "scene_switch_density": _fmt(para.get("scene_switch_density", "")),
        "dialogue_ratio_pct": _fmt(dlg.get("dialogue_ratio_pct", "")),
        "total_quotes": _fmt(dlg.get("total_quotes", "")),
        "dao_shuo_ratio": _fmt(dlg.get("dao_shuo_ratio", "")),
        "punc_comma": _fmt(punc_d.get("comma", "")),
        "punc_period": _fmt(punc_d.get("period", "")),
        "punc_exclamation": _fmt(punc_d.get("exclamation", "")),
        "punc_question": _fmt(punc_d.get("question", "")),
        "punc_ellipsis": _fmt(punc_d.get("ellipsis", "")),
        "punc_colon": _fmt(punc_d.get("colon", "")),
        "punc_dash": _fmt(punc_d.get("dash", "")),
        "comma_period_ratio": _fmt(punc_r.get("comma_period_ratio", "")),
        "exclamation_question_density": _fmt(punc_r.get("exclamation_question_density", "")),
        "metaphor_density": _fmt(rh.get("metaphor_density", "")),
        "rhetorical_question_density": _fmt(rh.get("rhetorical_question_density", "")),
        "parallelism_density": _fmt(rh.get("parallelism_density", "")),
        "third_person_count": _fmt(pov.get("third_person_count", "")),
        "first_person_count": _fmt(pov.get("first_person_count", "")),
        "action_count": _fmt(desc.get("action_count", "")),
        "mental_count": _fmt(desc.get("mental_count", "")),
        "env_count": _fmt(desc.get("env_count", "")),
        "action_mental_ratio": _fmt(desc.get("action_mental_ratio", "")),
        "driver_mode": _fmt(desc.get("driver_mode", "")),
    }
    # 低层测量层占位符（M080–M099）。字段缺失时整键不出现，占位符会保持未替换
    # 状态并被审计列出，而不是渲染成空串。
    low = quant.get("low_level_features", {}) or {}
    readability = low.get("readability", {}) or {}
    vocab = low.get("vocabulary_richness", {}) or {}
    complexity = low.get("sentence_complexity", {}) or {}
    sentiment = low.get("sentiment", {}) or {}
    pos_dist = low.get("pos_distribution", {}) or {}
    entities = low.get("named_entities", {}) or {}
    mapping.update({
        "readability_level": _fmt(readability.get("readability_level", "")),
        "avg_sentence_length_chars": _fmt(readability.get("avg_sentence_length_chars", "")),
        "avg_word_length_chars": _fmt(readability.get("avg_word_length_chars", "")),
        "gunning_fog_index": _fmt(readability.get("gunning_fog_index", "")),
        "yang_chengshu_index": _fmt(readability.get("yang_chengshu_index", "")),
        "flesch_kincaid_grade": _fmt(readability.get("flesch_kincaid_grade", "")),
        "smog_index": _fmt(readability.get("smog_index", "")),
        "complex_word_ratio": _fmt(readability.get("complex_word_ratio", "")),
        "ttr": _fmt(vocab.get("ttr", "")),
        "ttr_filtered": _fmt(vocab.get("ttr_filtered", "")),
        "hapax_ratio": _fmt(vocab.get("hapax_ratio", "")),
        "avg_clauses_per_sentence": _fmt(complexity.get("avg_clauses_per_sentence", "")),
        "subordinate_ratio": _fmt(complexity.get("subordinate_ratio", "")),
        "coordinate_ratio": _fmt(complexity.get("coordinate_ratio", "")),
        "sentiment_balance": _fmt(sentiment.get("sentiment_balance", "")),
        "entity_density": _fmt(entities.get("entity_density", "")),
        "verb_ratio": _fmt(pos_dist.get("verb_ratio", "")),
        "adjective_ratio": _fmt(pos_dist.get("adjective_ratio", "")),
    })
    return {k: v for k, v in mapping.items() if v != ""}


_TOKEN_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def substitute_placeholders(text: str, mapping: Dict[str, str]) -> str:
    """Replace known {{tokens}}; unknown tokens are left intact for auditing."""
    def repl(m: "re.Match[str]") -> str:
        key = m.group(1)
        return mapping.get(key, m.group(0))
    return _TOKEN_RE.sub(repl, text)


def find_unresolved_tokens(text: str) -> List[str]:
    """Return unknown/never-substituted placeholder tokens."""
    return sorted({m.group(1) for m in _TOKEN_RE.finditer(text)})


def render_placeholder_table(mapping: Dict[str, str]) -> str:
    """Markdown table of available placeholders, injected into the prompt."""
    lines = ["| 占位符 | 实测值 |", "|---|---|"]
    for k in sorted(mapping):
        lines.append(f"| {{{{{k}}}}} | {mapping[k]} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Numeric claim audit
# ---------------------------------------------------------------------------

def _num(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


# Each rule: (metric token, keyword regex capturing a number after it,
#             tolerance kind: 'rel'|'abs', tolerance value)
_AUDIT_RULES = [
    ("dialogue_ratio_pct", r"(?:对话字符占比|对话占比|对话比例)[^。；\n]{0,10}?(\d+(?:\.\d+)?)\s*%", "rel", 0.06),
    ("avg_sent_len", r"平均句长[^。；\n\d]{0,8}(\d+(?:\.\d+)?)\s*字", "abs", 1.5),
    ("median_sent_len", r"中位句长[^。；\n\d]{0,8}(\d+(?:\.\d+)?)\s*字", "abs", 2.0),
    ("avg_para_len", r"平均段(?:落)?长[^。；\n\d]{0,8}(\d+(?:\.\d+)?)\s*字", "abs", 3.0),
    ("short_sent_ratio_pct", r"短句率[^。；\n]{0,12}?(\d+(?:\.\d+)?)\s*%", "rel", 0.08),
    ("long_sent_ratio_pct", r"长句率[^。；\n]{0,12}?(\d+(?:\.\d+)?)\s*%", "rel", 0.08),
    ("short_para_ratio_pct", r"极短段率?[^。；\n]{0,12}?(\d+(?:\.\d+)?)\s*%", "rel", 0.08),
    # /千字 断言与 punc_* 系列同口径：不写单位时"场景切换密度每章 5 次"这类
    # 合法叙述会被误报成指标冲突（scene_switch 为非核心指标，仅 warning，
    # 但 warning 噪声同样会淹没有效提示）。
    ("scene_switch_density", r"场景切换密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)\s*(?:次)?\s*/?\s*千字", "rel", 0.08),
    ("metaphor_density", r"比喻(?:句)?密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)\s*(?:次)?\s*/?\s*千字", "rel", 0.08),
    ("rhetorical_question_density", r"反问(?:句)?密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.10),
    ("parallelism_density", r"排比(?:句)?密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.12),
    ("comma_period_ratio", r"逗[号句][/与和]?句[号]?比[^。；\n\d]{0,6}(\d+(?:\.\d+)?)\s*[:：]?\s*(?:1)?", "rel", 0.08),
    ("punc_comma", r"逗号密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.08),
    ("punc_period", r"句号密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.08),
    ("punc_exclamation", r"感叹号密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.08),
    ("punc_question", r"问号密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.08),
    ("punc_ellipsis", r"省略号密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.08),
    ("punc_dash", r"破折号密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.08),
    ("action_mental_ratio", r"动作[:：/]?(?:心理|与心理)比[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.08),
    ("total_chars", r"(?:总字符数|总字符|字符总数)[^。；\n\d]{0,6}?(\d[\d,]*)\s*(?:字符|字)", "rel", 0.02),
    ("third_person_count", r"第三人称[^。；\n\d]{0,6}?(\d[\d,]*)\s*次", "rel", 0.06),
    ("first_person_count", r"第一人称[^。；\n\d]{0,6}?(\d[\d,]*)\s*次", "rel", 0.06),
    # 低层测量指标：启发式/分词依赖，容差放宽且不在 CORE_AUDIT_TOKENS 内，
    # 冲突只提示不阻断（见 METRIC_DEFS 上方说明）。
    ("ttr", r"(?:类符形符比|词汇丰富度|TTR)[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.20),
    ("ttr_filtered", r"(?:过滤后TTR|实词丰富度)[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.20),
    ("hapax_ratio", r"(?:低频词|仅出现一次的词)占比[^。；\n\d]{0,6}(\d+(?:\.\d+)?)\s*%?", "rel", 0.25),
    ("avg_clauses_per_sentence", r"平均每句(?:分句|小句)数[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.15),
    ("entity_density", r"(?:命名)?实体密度[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.25),
    ("complex_word_ratio", r"复杂词占比[^。；\n\d]{0,6}(\d+(?:\.\d+)?)\s*%?", "rel", 0.25),
    ("sentiment_balance", r"情感(?:平衡|倾向)值[^。；\n\d\-]{0,6}(-?\d+(?:\.\d+)?)", "abs", 0.25),
    ("gunning_fog_index", r"(?:Gunning[- ]?Fog|枪雾指数|古宁雾指数)[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.25),
    ("smog_index", r"SMOG[^。；\n\d]{0,6}(\d+(?:\.\d+)?)", "rel", 0.25),
]

# Hard-fail metrics: the load-bearing numbers a reader would use to actually
# replicate the style. Everything else downgrades to a warning so explanatory
# prose is not strangled by the audit.
CORE_AUDIT_TOKENS = {
    "avg_sent_len",
    "avg_para_len",
    "dialogue_ratio_pct",
    "short_sent_ratio_pct",
    "long_sent_ratio_pct",
    "metaphor_density",
    "comma_period_ratio",
    "action_mental_ratio",
}

_QUOTE_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?\[[a-zA-Z0-9_-]+\]")


def audit_numeric_claims(
    prose: str,
    quant: Dict[str, Any],
    mapping: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """
    Detect bare numbers contradicting measured values near metric keywords.

    Only lines that are not evidence-quote lines are audited. Returns a list of
    conflict dicts; core-metric conflicts carry ``severity: "error"`` (block the
    report), the rest ``severity: "warning"``. Empty list means fully clean.
    """
    mapping = mapping or build_placeholder_map(quant)

    # Reverse lookup: measured string -> float, per token
    measured: Dict[str, float] = {}
    for token, raw in mapping.items():
        v = _num(raw.rstrip("%"))
        if v is not None:
            measured[token] = v

    conflicts: List[Dict[str, str]] = []
    for line in prose.splitlines():
        if _QUOTE_LINE_RE.match(line):
            continue
        # 占位符本身已由替换绑定实测值，掩码后仍审计同行其余数字——
        # 同一行混入合法占位符与伪造数字的情况不允许逃过审计。
        if "{{" in line:
            line = _TOKEN_RE.sub("", line)
        conflicts.extend(_audit_line(line, measured, mapping))
    return conflicts


def _audit_line(
    line: str,
    measured: Dict[str, float],
    mapping: Dict[str, str],
) -> List[Dict[str, str]]:
    conflicts: List[Dict[str, str]] = []
    for token, pattern, tol_kind, tol_val in _AUDIT_RULES:
            for match in re.finditer(pattern, line):
                written = _num(match.group(1))
                target = measured.get(token)
                if written is None or target is None:
                    continue
                if tol_kind == "rel":
                    ok = abs(written - target) <= max(abs(target) * tol_val, 0.02)
                else:
                    ok = abs(written - target) <= tol_val
                if not ok:
                    conflicts.append({
                        "token": token,
                        "written": match.group(1),
                        "measured": mapping.get(token, "?"),
                        "context": line.strip()[:80],
                        "severity": "error" if token in CORE_AUDIT_TOKENS else "warning",
                    })
    return conflicts


def audit_json_numeric_claims(
    data: Any,
    quant: Dict[str, Any],
    mapping: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """审计 JSON 结构字段中的裸数字（技法卡与思维层）。

    证据 quote/note 引用原文，跳过；desensitization_map 为原型标签，跳过；
    其余字符串字段（definition/trigger/steps/boundary/counterexample/思维层）
    出现与实测冲突的核心指标即拒绝。
    """
    if not isinstance(data, dict):
        return []
    mapping = mapping or build_placeholder_map(quant)
    measured: Dict[str, float] = {}
    for token, raw in mapping.items():
        v = _num(str(raw).rstrip("%"))
        if v is not None:
            measured[token] = v
    conflicts: List[Dict[str, str]] = []

    def walk(node: Any, path: str, parent_key: str) -> None:
        if isinstance(node, dict):
            for raw_key, raw_value in node.items():
                key = str(raw_key)
                if key == "desensitization_map":
                    continue
                if key in {"quote", "note"} and parent_key == "evidence":
                    continue
                walk(raw_value, f"{path}.{key}", key)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]", parent_key)
        elif isinstance(node, str):
            for token, pattern, tol_kind, tol_val in _AUDIT_RULES:
                for match in re.finditer(pattern, node):
                    written = _num(match.group(1))
                    target = measured.get(token)
                    if written is None or target is None:
                        continue
                    if tol_kind == "rel":
                        ok = abs(written - target) <= max(abs(target) * tol_val, 0.02)
                    else:
                        ok = abs(written - target) <= tol_val
                    if not ok:
                        conflicts.append({
                            "token": token,
                            "written": match.group(1),
                            "measured": mapping.get(token, "?"),
                            "context": f"{path}: {node[:60]}",
                            "severity": "error" if token in CORE_AUDIT_TOKENS else "warning",
                        })

    walk(data, "", "")
    return conflicts


# ---------------------------------------------------------------------------
# Metric name registry (for technique-card evidence.metric checks)
# ---------------------------------------------------------------------------

METRIC_ALIASES: Dict[str, Tuple[str, ...]] = {
    "avg_sent_len": ("平均句长", "句长"),
    "median_sent_len": ("中位句长",),
    "short_sent_ratio": ("短句率", "短句占比"),
    "long_sent_ratio": ("长句率", "长句占比"),
    "avg_para_len": ("平均段长", "段落长度"),
    "short_para_ratio": ("极短段率", "短段率"),
    "dialogue_ratio": ("对话占比", "对话比例", "对话率"),
    "dao_shuo_ratio": ("道说比", "道:说"),
    "tag_frequencies": ("标签频次", "对话标签"),
    "punc_exclamation": ("感叹号",),
    "punc_question": ("问号",),
    "punc_ellipsis": ("省略号",),
    "punc_dash": ("破折号",),
    "comma_period_ratio": ("逗句比", "逗号句号比"),
    "metaphor_density": ("比喻",),
    "rhetorical_question_density": ("反问",),
    "parallelism_density": ("排比",),
    "pov_pronouns": ("视角", "人称代词", "第一人称", "第三人称"),
    "description_density": ("描写密度", "动作心理比", "环境描写",
                            "action_mental_ratio", "action_count", "env_count", "mental_count"),
    "imagery_clusters": ("意象", "高频词"),
}


def metric_token_from_label(label: str) -> Optional[str]:
    """Resolve a metric label to a registry token.

    Two input forms are accepted:

    1. **Canonical registry tokens** — ``punc_dash``, ``short_sent_ratio_pct``,
       ``action_mental_ratio``. This is the form documented in
       ``references/report-schema.md`` and used throughout ``assets/examples``,
       i.e. what the analysis LLM is instructed to emit.
    2. **Chinese display aliases** — ``破折号``, ``短句率``, for hand-written input.

    A trailing ``_pct`` display suffix is tolerated (``short_sent_ratio_pct``
    resolves to ``short_sent_ratio``) because the placeholder registry exposes
    percentage-bearing fields under that name.
    """
    label_l = label.strip().lower()
    if not label_l:
        return None
    # 1) Canonical token. _METRIC_PATHS is defined below this function but is a
    #    module-level name, so it is resolved lazily at call time.
    candidates = [label_l]
    if label_l.endswith("_pct"):
        candidates.append(label_l[:-4])
    for candidate in candidates:
        if candidate in _METRIC_PATHS:
            return candidate
    # 2) Chinese (and derived-metric English) aliases.
    for token, aliases in METRIC_ALIASES.items():
        if any(a in label_l for a in aliases):
            return token
    return None


_METRIC_PATHS: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    "avg_sent_len": (("sentence_structure", "avg_sent_len"),),
    "median_sent_len": (("sentence_structure", "median_sent_len"),),
    "short_sent_ratio": (("sentence_structure", "short_sent_ratio_pct"), ("sentence_structure", "short_sent_ratio")),
    "long_sent_ratio": (("sentence_structure", "long_sent_ratio_pct"), ("sentence_structure", "long_sent_ratio")),
    "avg_para_len": (("paragraph_rhythm", "avg_para_len"),),
    "short_para_ratio": (("paragraph_rhythm", "short_para_ratio_pct"), ("paragraph_rhythm", "short_para_ratio")),
    "scene_switch_density": (("paragraph_rhythm", "scene_switch_density"),),
    "dialogue_ratio": (("dialogue_features", "dialogue_ratio_pct"), ("dialogue_features", "dialogue_ratio")),
    "dao_shuo_ratio": (("dialogue_features", "dao_shuo_ratio"),),
    "tag_frequencies": (("dialogue_features", "tag_frequencies"),),
    "punc_exclamation": (("punctuation_density", "exclamation"),),
    "punc_question": (("punctuation_density", "question"),),
    "punc_ellipsis": (("punctuation_density", "ellipsis"),),
    "punc_dash": (("punctuation_density", "dash"),),
    "punc_comma": (("punctuation_density", "comma"),),
    "punc_period": (("punctuation_density", "period"),),
    "punc_colon": (("punctuation_density", "colon"),),
    "comma_period_ratio": (("punctuation_ratios", "comma_period_ratio"),),
    "exclamation_question_density": (("punctuation_ratios", "exclamation_question_density"),),
    "metaphor_density": (("rhetoric_features", "metaphor_density"),),
    "rhetorical_question_density": (("rhetoric_features", "rhetorical_question_density"),),
    "parallelism_density": (("rhetoric_features", "parallelism_density"),),
    "pov_pronouns": (("perspective_and_narration", "pov_tendency"),),
    "third_person_count": (("perspective_and_narration", "third_person_count"),),
    "first_person_count": (("perspective_and_narration", "first_person_count"),),
    "description_density": (("description_density", "action_count"), ("description_density", "env_count")),
    "action_mental_ratio": (("description_density", "action_mental_ratio"),),
    "imagery_clusters": (("imagery_clusters",),),
}


def metric_token_present(label: str, quantitative_features: Dict[str, Any]) -> bool:
    """Return whether an evidence label resolves to a field measured this run."""
    token = metric_token_from_label(label)
    if not token or not isinstance(quantitative_features, dict):
        return False
    for path in _METRIC_PATHS.get(token, ()):
        current: Any = quantitative_features
        try:
            for part in path:
                if not isinstance(current, dict) or part not in current:
                    raise KeyError(part)
                current = current[part]
            if current not in (None, "", {}, []):
                return True
        except KeyError:
            continue
    return False
