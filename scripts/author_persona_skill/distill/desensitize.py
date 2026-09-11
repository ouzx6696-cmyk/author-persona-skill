# -*- coding: utf-8 -*-
"""Desensitization engine: candidate extraction, mapping application, and reverse leak validation.

Candidate sources are deliberately narrow: top dialogue speakers, 《》bracketed
worldview terms, and author/work identity. Generic-word harvesting is excluded
by design to keep false positives and truncated pseudo-nouns out of reports.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from ..analyzers.dialogue_analyzer import SPEAKER_VERB_SUFFIXES


# Generic stop words that never qualify as proper nouns. Kept small on purpose:
# it guards the dialogue-tag extractor against verb/pronoun artifacts, not a
# patch wall against a broken candidate heuristic.
COMMON_WHITELIST = {
    # 对话标签动词（与正则动词集互补的复合形式）
    "道", "说", "问", "答", "喊", "叹", "笑",
    "说道", "问道", "答道",
    # 代词与高频功能词
    "一个", "这个", "他们", "我们", "自己", "什么", "怎么", "没有", "知道",
    # 泛称角色词（可出现在说话人位但不是专名）
    "主角", "导师", "前辈", "长辈", "少年", "少女", "老者", "青年", "同伴", "敌人",
    "大人", "先生", "姑娘", "皇帝", "陛下", "夫人", "王爷", "大臣", "将军",
}

# Verbs/adverbs glued to a speaker name by the tag window (e.g. 罗兰点 /
# 她摇头 / 弗朗茨微笑 / 菲尔德回答). Stripped iteratively until stable.
# Word list lives in analyzers.dialogue_analyzer (SPEAKER_VERB_SUFFIXES).

_DIALOGUE_TAG_RE = re.compile(
    r'([“"”\']\s*[\u4e00-\u9fa5A-Za-z0-9，。！？…—]{1,80}[”"\'"]\s*)([\u4e00-\u9fa5]{2,4})([道说问答喊笑喝叹骂吼])|'
    r'([\u4e00-\u9fa5]{2,4})([道说问答喊笑喝叹骂吼])(\s*[“"”\'][\u4e00-\u9fa5A-Za-z0-9，。！？…—]{1,80}[”"\'"])'
)

_TITLE_BRACKET_RE = re.compile(r'《([\u4e00-\u9fa5A-Za-z0-9]{2,12})》')


def _clean_speaker(raw: str) -> str:
    name = raw.strip()
    verbs = SPEAKER_VERB_SUFFIXES  # already sorted longest-first
    changed = True
    while changed:
        changed = False
        for v in verbs:
            if name.endswith(v) and len(name) > len(v):
                name = name[:-len(v)].strip()
                changed = True
                break
    return name


def _is_plausible_name(name: str) -> bool:
    if not name or len(name) < 2 or name in COMMON_WHITELIST:
        return False
    if name.endswith(("知道", "说道", "古道", "写道", "报道", "味道")):
        return False
    if any(c in name for c in "的了吗是在有和就个也这那都很到上过得着"):
        return False
    return True


def extract_proper_noun_candidates(
    text: str,
    top_n: int = 50,
    author_name: str = "",
    work_title: str = "",
    max_speakers: int = 3,
    max_bracket_terms: int = 5,
    speakers: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Collect desensitization watch-list candidates from two reliable sources only:
    the most frequent dialogue speakers (top ``max_speakers``, taken from the
    dialogue analyzer when ``speakers`` is given) and 《》bracketed worldview
    terms (top ``max_bracket_terms``). Author/work identity is always included
    so reverse validation can guard it.
    """
    if speakers:
        ranked = sorted(
            (s for s in speakers if isinstance(s, dict)),
            key=lambda s: s.get("occurrences", 0),
            reverse=True,
        )
        speaker_entries = [
            {"term": str(s.get("name", "")).strip(), "score": int(s.get("occurrences", 0)) * 5, "suggested_type": "character"}
            for s in ranked[:max_speakers]
            if str(s.get("name", "")).strip() and int(s.get("occurrences", 0)) >= 2
        ]
    else:
        counts: Counter[str] = Counter()
        for m in _DIALOGUE_TAG_RE.finditer(text):
            name = _clean_speaker(m.group(2) or m.group(4) or "")
            if _is_plausible_name(name):
                counts[name] += 1
        speaker_entries = [
            {"term": name, "score": freq * 5, "suggested_type": "character"}
            for name, freq in counts.most_common(max_speakers)
        ]

    brackets: Counter[str] = Counter()
    for m in _TITLE_BRACKET_RE.finditer(text):
        term = m.group(1)
        if term and term not in COMMON_WHITELIST:
            brackets[term] += 1

    result: List[Dict[str, Any]] = []
    if author_name and len(author_name) >= 2:
        result.append({"term": author_name, "score": 1000, "suggested_type": "author_identity"})
    if work_title and len(work_title) >= 2:
        result.append({"term": work_title, "score": 999, "suggested_type": "work_identity"})
    result.extend(speaker_entries)
    for term, freq in brackets.most_common(max_bracket_terms):
        result.append({"term": term, "score": freq * 10, "suggested_type": "worldview_term"})
    return [c for c in result if c["term"]][:top_n]


# ---------------------------------------------------------------------------
# Term matching
# ---------------------------------------------------------------------------
# ASCII identity terms need word boundaries. A work title derived from the file
# name (e.g. "corpus") otherwise matches the structural identifier
# "full_corpus" inside the metric registry, which is neither text nor an
# identity — that false positive blocked an otherwise valid report. CJK has no
# word boundaries, so CJK terms keep plain substring matching.
_ASCII_TERM_RE = re.compile(r"^[A-Za-z0-9_ ]+$")


def term_pattern(term: str) -> str:
    """Regex source matching one identity term with appropriate boundaries."""
    escaped = re.escape(term)
    if term.isascii() and _ASCII_TERM_RE.match(term):
        # Underscore counts as a word character so machine identifiers such as
        # "full_corpus" are not mistaken for the term "corpus".
        return rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
    return escaped


def count_term(text: str, term: str) -> int:
    """Occurrences of ``term`` in ``text``, boundary-aware for ASCII terms."""
    if not text or not term:
        return 0
    return len(re.findall(term_pattern(term), text))


def apply_desensitization(text: str, mapping: Dict[str, str]) -> str:
    """Replace mapped terms, longest-first, without replacement cascades."""
    if not mapping or not text:
        return text
    keys = [
        key for key in sorted(mapping, key=len, reverse=True)
        if key and key not in COMMON_WHITELIST and mapping.get(key) and mapping[key] != key
    ]
    if not keys:
        return text
    pattern = re.compile("|".join(term_pattern(key) for key in keys))
    return pattern.sub(lambda match: str(mapping[match.group(0)]), text)


# 锚点切分：一行内可能出现多条 [id] “…” 证据，先按锚点切开再逐段遮蔽，
# 否则贪婪匹配会把后一条锚点一起吞掉。
_ANCHOR_SPLIT_RE = re.compile(r"(?=\[[a-zA-Z0-9_-]+\]\s*[“\"'「『])")
# 段内遮蔽必须吃到该段**最后一个**引号。引文自身常含成对引号
# （如 “……。”XX道，……。），非贪婪写法的 .*? 只盖住第一对，把后半句原文
# 连同未配对的右引号留在公开产物里——既泄漏原作内容，也破坏 Markdown 结构。
# 渲染层（report/renderer.py）与校验层（validate_desensitization）共用本正则，
# 否则会出现"渲染已遮蔽、校验仍判泄漏"的矛盾拒绝。
_EVIDENCE_LINE_RE = re.compile(
    r"(\[[a-zA-Z0-9_-]+\]\s*[“\"'「『])(.*)([”\"'」』])"
)
# 注解字段边界：证据行格式为 “quote” (metric) — 注解：note。
# 贪婪匹配必须止步于该边界——note 元信息里出现任意闭合类引号（如 '）时，
# 无边界的贪婪会把 metric 与「注解：」前缀一并吞进占位符，产物静默损坏。
_NOTE_FIELD_RE = re.compile(r"—\s*注解：|注解：")


def mask_evidence_quotes(text: str, placeholder: str = "") -> str:
    """遮蔽锚点证据行里的引文正文，保留锚点与行尾注解。

    渲染层传占位符生成公开产物；校验层传空串把引文整段剔除，再对剩余
    文本做泄漏检测（引文本身豁免，未映射专名出现在引文中不算泄漏）。
    """
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        if not _ANCHOR_SPLIT_RE.search(line):
            lines.append(line)
            continue
        rebuilt = []
        for part in _ANCHOR_SPLIT_RE.split(line):
            if _ANCHOR_SPLIT_RE.match(part):
                part = _mask_anchored_part(part, placeholder)
            rebuilt.append(part)
        lines.append("".join(rebuilt))
    return "\n".join(lines)


def _mask_anchored_part(part: str, placeholder: str) -> str:
    """遮蔽单个锚点段：引文贪婪遮蔽止步于注解边界，注解内容原样保留。

    注解是 LLM 元信息而非原文引用，其中的引号词不得被占位符吞掉
    （专名泄漏由身份词扫描兜底）。fail-closed：若遮蔽后「注解：」前缀
    消失，说明正则吞并了注解字段，应拒绝而非产出损坏的公开报告。
    """
    boundary = _NOTE_FIELD_RE.search(part)
    if boundary:
        head, note = part[:boundary.start()], part[boundary.start():]
    else:
        head, note = part, ""
    head = _EVIDENCE_LINE_RE.sub(
        lambda m: m.group(1) + placeholder + m.group(3), head, count=1
    )
    masked = head + note
    if _NOTE_FIELD_RE.search(part) and not _NOTE_FIELD_RE.search(masked):
        raise ValueError(
            "证据行遮蔽吞并「注解：」前缀（正则越界），拒绝渲染损坏产物: "
            + part[:80]
        )
    return masked


def strip_evidence_quotes(text: str) -> str:
    """Mask *every* quoted span on anchored evidence lines.

    The substitution must cover all quotes on the line: a second
    ``[cNN] “…”`` pair is otherwise neither exempted from leak detection
    nor hidden from the public artifact.
    """
    return mask_evidence_quotes(text)


def validate_desensitization_map(
    mapping: Any,
    proper_noun_candidates: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate mapping shape without treating extra keys as hard errors."""
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if not isinstance(mapping, dict):
        return ([{"type": "mapping_not_object", "reason": "desensitization_map must be an object"}], [])

    candidate_terms = {
        str(item.get("term", "")).strip()
        for item in proper_noun_candidates
        if isinstance(item, dict) and str(item.get("term", "")).strip()
    }
    all_originals = candidate_terms | set(str(k).strip() for k in mapping if str(k).strip())
    for original, replacement in mapping.items():
        original = str(original).strip()
        replacement = str(replacement).strip()
        if not original:
            errors.append({"type": "empty_mapping_key", "reason": "映射键不能为空"})
            continue
        if not replacement:
            errors.append({"term": original, "type": "empty_mapping_value", "reason": "映射替换值不能为空"})
        elif replacement == original:
            errors.append({"term": original, "type": "identity_mapping", "reason": "映射替换值必须与原文不同"})
        if original not in candidate_terms and original not in {"",}:
            warnings.append({"term": original, "type": "mapping_not_in_candidates", "reason": "映射键不在候选专名词典中"})
        if replacement and not (2 <= len(replacement) <= 4):
            warnings.append({
                "term": original,
                "type": "label_length",
                "reason": f"替换标签 {replacement} 长度 {len(replacement)} 字，建议 2–4 字中性原型词",
            })
        leaked_sources = [term for term in all_originals if len(term) >= 2 and term != original and term in replacement]
        if leaked_sources:
            errors.append({"term": original, "type": "mapping_value_leak", "reason": f"替换值包含原文术语：{', '.join(leaked_sources)}"})
    return errors, warnings


def validate_desensitization_json(
    value: Any,
    proper_noun_candidates: List[Dict[str, Any]],
    author_name: str = "",
    work_title: str = "",
) -> List[Dict[str, Any]]:
    """Find identity leaks in structured report values, excluding raw quote anchors."""
    return scan_artifact(value, proper_noun_candidates, author_name, work_title)


def build_forbidden_identities(
    proper_noun_candidates: List[Dict[str, Any]],
    author_name: str = "",
    work_title: str = "",
) -> List[str]:
    """Author/work are always forbidden. No empty-title bypass."""
    terms: List[str] = []
    for item in proper_noun_candidates or []:
        if isinstance(item, dict):
            term = str(item.get("term", "")).strip()
            if len(term) >= 2 and term not in terms:
                terms.append(term)
    for term in (author_name, work_title):
        if term and len(str(term).strip()) >= 2 and str(term).strip() not in terms:
            terms.append(str(term).strip())
    return terms


def scan_artifact(
    value: Any,
    proper_noun_candidates: List[Dict[str, Any]] | None = None,
    author_name: str = "",
    work_title: str = "",
    _path: str = "",
    _parent_key: str = "",
) -> List[Dict[str, Any]]:
    """Unified recursive leak scanner for ALL artifacts.

    Walks every string node — dict keys, dict values, list items, filenames,
    error messages. Keys are scanned as well as values: a structured map can
    carry an identity in its key (``imagery_clusters`` is keyed by high-frequency
    words), and a value-only scan left that path invisible.

    ``quote`` under ``evidence`` stays exempt (the raw anchor lives in the
    private sidecar only). ``desensitization_map`` keys are exempt (originals are
    expected there); its values are still checked. ``discarded_candidates`` is
    exempt because copying candidate words there is the field's documented use.
    """
    terms = build_forbidden_identities(
        list(proper_noun_candidates or []), author_name, work_title)

    leaks: List[Dict[str, Any]] = []

    def scan_string(text: str, path: str) -> None:
        for term in terms:
            count = count_term(text, term)
            if count:
                leaks.append({
                    "term": term,
                    "type": "structured_identity_leak",
                    "count": count,
                    "path": path,
                    "reason": f"Identity term '{term}' found in structured field {path}",
                })

    def walk(node: Any, path: str = "", parent_key: str = "") -> None:
        if isinstance(node, dict):
            for raw_key, raw_value in node.items():
                key = str(raw_key)
                if key == "desensitization_map":
                    for map_value in (raw_value.values() if isinstance(raw_value, dict) else []):
                        walk(map_value, f"{path}.{key}", key)
                    continue
                if key == "quote" and parent_key == "evidence":
                    continue
                if key == "discarded_candidates":
                    continue
                scan_string(key, f"{path}.{key}")
                walk(raw_value, f"{path}.{key}", key)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]", parent_key)
        elif isinstance(node, str):
            scan_string(node, path)

    walk(value, _path, _parent_key)
    return leaks


def compute_work_id(author_name: str = "", work_title: str = "") -> str:
    """Stable pseudonymous work identifier (no real title in filenames)."""
    import hashlib
    seed = f"{author_name or ''}|{work_title or ''}".strip("|")
    if not seed:
        return "WORK_UNKNOWN"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6].upper()
    return f"WORK_{digest}"


def validate_desensitization(
    report_body: str,
    proper_noun_candidates: List[Dict[str, Any]],
    author_name: str = "",
    work_title: str = "",
    whitelist: Optional[Set[str]] = None,
    ignore_evidence_quotes: bool = True,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Reverse validation:
    Top proper nouns and author/work identifiers must not leak in the report body.
    Returns (is_passed, leaked_items).
    """
    wl = set(COMMON_WHITELIST)
    if whitelist:
        wl.update(whitelist)

    body_to_check = strip_evidence_quotes(report_body) if ignore_evidence_quotes else report_body

    leaks: List[Dict[str, Any]] = []

    # Check author and work identities. They are allowed in explicit metadata,
    # but never in the report body being validated.
    identity_terms = [(author_name, "author_identity_leak"), (work_title, "work_identity_leak")]
    for identity, identity_type in identity_terms:
        if identity and len(identity) >= 2:
            count = count_term(body_to_check, identity)
            if count:
                leaks.append({
                    "term": identity,
                    "type": identity_type,
                    "count": count,
                    "reason": f"Identity term '{identity}' found {count} time(s) in report body",
                })

    # Candidate validation below deliberately skips the author identity entry;
    # it was already checked once in the identity pass above.
    # Check top candidates
    for item in proper_noun_candidates:
        term = item.get("term", "")
        if not term or term in wl or len(term) < 2:
            continue
        if term == author_name:
            continue
        count = count_term(body_to_check, term)
        if count > 0:
            leaks.append({
                "term": term,
                "type": item.get("suggested_type", "proper_noun"),
                "count": count,
                "score": item.get("score", 0),
                "reason": f"Original proper noun '{term}' leaked {count} time(s)",
            })

    passed = len(leaks) == 0
    return (passed, leaks)
