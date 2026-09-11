# -*- coding: utf-8 -*-
"""Evidence anchor extraction, candidate pool building, and quote verification."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ..analyzers.rhetoric import find_simile_sentences


def normalize_quote(text: str) -> str:
    """Normalize whitespace and punctuation quotes for resilient matching."""
    text = re.sub(r'\s+', '', text)
    text = text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
    text = text.replace('—', '-').replace('…', '...')
    return text


def create_chunks(text: str, chunk_size: int = 2000, chunk_prefix: str = "c") -> Dict[str, str]:
    """Split corpus text into indexed chunks."""
    lines = text.splitlines(keepends=True)
    chunks: Dict[str, str] = {}
    current_chunk: List[str] = []
    current_len = 0
    chunk_idx = 1

    for line in lines:
        current_chunk.append(line)
        current_len += len(line)
        if current_len >= chunk_size:
            cid = f"{chunk_prefix}{chunk_idx:03d}"
            chunks[cid] = "".join(current_chunk)
            chunk_idx += 1
            current_chunk = []
            current_len = 0

    if current_chunk:
        cid = f"{chunk_prefix}{chunk_idx:03d}"
        chunks[cid] = "".join(current_chunk)

    return chunks


_ANCHOR_SENT_SPLIT = re.compile(r"[。！？\n]")
_DASH_RE = re.compile(r"——")
_ELLIPSIS_SENT_RE = re.compile(r"……[^…\n]")
# Dialogue-tag anchors only need the line, not a clean speaker name. Two loose
# patterns cover the real-world formats: "人名道：『……』" (tag first) and
# "……！」人名说道" (tag last, possibly with an adverb infix like 胸有成竹的).
_DIALOGUE_TAG_FRONT_RE = re.compile(
    r"(?:说道|问道|答道|笑道|摇头|点头|回答|开口|说|道)[，：]?[“「『]"
)
_DIALOGUE_TAG_REAR_RE = re.compile(
    r"[”」』][，。！？…]?\S{0,40}(?:说道|问道|答道|笑道|说|道)"
)
_EXEMPLIFY_RE = re.compile(r"(?:比如说|例如|譬如)")
_SHORT_PARA_MIN = 2
_SHORT_PARA_MAX = 8

#: 引文回验最短门槛：任何 ≥6 字的原文片段才可能成为「已验证锚点」。
#: 旧值 2 等于放行任意双字片段（如人名）冒充证据。候选池的入选下限
#: （``_MIN_POOL_ANCHOR_LEN``）必须与它一致，否则池子会诱导 LLM 选到
#: 注定被降级的锚点。这是模块常量，可回调。
MIN_QUOTE_CHARS = 6
_MIN_POOL_ANCHOR_LEN = MIN_QUOTE_CHARS

# Light garble heuristic: anchor candidates that look like OCR/精校 corruption
# are skipped (semantic-level corruption cannot be fully detected stdlib-only;
# this catches the common enumeration-without-function-word pattern). Lines
# carrying dialogue quotes or speech tags are exempt -- dialogue is legitimately
# terse and would otherwise be misflagged as garble.
_GARBLE_RE = re.compile(r"[的地得了着在和与]")
_DIALOGUE_LINE_RE = re.compile(r"[“”「」『』\"']|(?:说道|问道|答道|笑道|说|道|问|答)")


def _is_suspect_garbled(sentence: str) -> bool:
    if _DIALOGUE_LINE_RE.search(sentence):
        return False
    return len(sentence) > 12 and not _GARBLE_RE.search(sentence)


def _chunk_candidates(cid: str, chunk_text: str) -> List[Dict[str, Any]]:
    """Extract mixed-type anchor candidates from a single chunk (small, diverse)."""
    candidates: List[Dict[str, Any]] = []

    for s in find_simile_sentences(chunk_text):
        if not _is_suspect_garbled(s):
            candidates.append({"chunk_id": cid, "quote": s, "type": "metaphor_anchor", "signal": "修辞比喻例证（显式喻词）"})
            break

    for raw in _ANCHOR_SENT_SPLIT.split(chunk_text):
        s = raw.strip().strip("，、；：")
        if 8 <= len(s) <= 60 and _DASH_RE.search(s) and not _ELLIPSIS_SENT_RE.search(s):
            if not _is_suspect_garbled(s):
                candidates.append({"chunk_id": cid, "quote": s, "type": "dash_anchor", "signal": "破折号插入/转折功能例"})
            break

    for raw in _ANCHOR_SENT_SPLIT.split(chunk_text):
        s = raw.strip().strip("，、；：")
        if 8 <= len(s) <= 60 and _ELLIPSIS_SENT_RE.search(s):
            if not _is_suspect_garbled(s):
                candidates.append({"chunk_id": cid, "quote": s, "type": "ellipsis_anchor", "signal": "省略号迟疑/悬停功能例"})
            break

    for line in chunk_text.splitlines():
        s = line.strip()
        if len(s) <= 80 and (_DIALOGUE_TAG_FRONT_RE.search(s) or _DIALOGUE_TAG_REAR_RE.search(s)):
            if not _is_suspect_garbled(s):
                candidates.append({"chunk_id": cid, "quote": s, "type": "dialogue_tag_anchor", "signal": "对话标签用法例"})
            break

    for line in chunk_text.splitlines():
        s = line.strip().strip("，、；： ")
        if _SHORT_PARA_MIN <= len(s) <= _SHORT_PARA_MAX and s.endswith(("。", "！", "？")):
            candidates.append({"chunk_id": cid, "quote": s, "type": "short_para_anchor", "signal": "极短段重锤例"})
            break

    for raw in _ANCHOR_SENT_SPLIT.split(chunk_text):
        s = raw.strip().strip("，、；：")
        if 8 <= len(s) <= 60 and _EXEMPLIFY_RE.search(s):
            if not _is_suspect_garbled(s):
                candidates.append({"chunk_id": cid, "quote": s, "type": "exemplification_anchor", "signal": "比如说/例如 具象转译例"})
            break

    # Deterministic rotation so successive chunks lead with different types.
    rotation = sum(ord(c) for c in cid) % len(candidates) if candidates else 0
    return candidates[rotation:] + candidates[:rotation]


def extract_candidate_evidence_pool(
    chunks: Dict[str, str],
    max_items: int = 15,
    era_map: Optional[Dict[str, str]] = None,
    era_id_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Build the candidate evidence pool.

    Anchors are drawn round-robin across era groups (or all chunks when no era
    map is given) so the pool spans the whole sampling range instead of only
    the opening chunks. Each anchor carries its era label when known, plus a
    stable evidence_id (E0001...) and era_id, so the LLM can cite IDs instead
    of copying quotes. No
    per-type quota is enforced: the pool is a candidate menu for the LLM, and
    forced type balancing produced padding evidence nobody asked for.
    """
    groups: Dict[str, List[str]] = defaultdict(list)
    for cid in sorted(chunks.keys()):
        era = (era_map or {}).get(cid, "未分期")
        groups[era].append(cid)
    if not groups:
        # 空语料（全被降噪等）直接返回空池，交由上游报错，不做除零
        return []

    per_group = max(1, -(-max_items // len(groups)))  # ceil division

    pool: List[Dict[str, Any]] = []
    group_progress = {era: 0 for era in groups}
    group_quotas = {era: per_group for era in groups}

    while len(pool) < max_items:
        progressed = False
        for era in sorted(groups.keys()):
            if len(pool) >= max_items or group_quotas.get(era, 0) <= 0:
                continue
            cids = groups[era]
            idx = group_progress[era]
            if idx >= len(cids):
                continue
            cid = cids[idx]
            group_progress[era] += 1
            progressed = True

            for cand in _chunk_candidates(cid, chunks[cid]):
                if len(pool) >= max_items or group_quotas[era] <= 0:
                    break
                # 池级过滤：短于 6 字回验门槛的锚点（如「嘭！」）引用必被
                # 降级，放进池里只会诱导 LLM 选到无法通过回验的证据。
                if len(str(cand.get("quote", "")).strip()) < _MIN_POOL_ANCHOR_LEN:
                    continue
                cand = dict(cand)
                cand["era"] = era
                if era_id_map:
                    cand["era_id"] = str(era_id_map.get(cid, ""))
                pool.append(cand)
                group_quotas[era] -= 1
        if not progressed:
            break

    # Stable Evidence IDs. LLM cites EIDs; Renderer resolves text.
    for i, item in enumerate(pool, 1):
        item.setdefault("evidence_id", f"E{i:04d}")
    return pool


def build_evidence_store(
    pool: List[Dict[str, Any]],
    chunks: Dict[str, str],
    chunk_offsets: Optional[Dict[str, int]] = None,
    era_spans: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build Trusted Evidence Store: EID -> {text, chunk_id, era, era_id, offsets}.

    Offsets are global sampled_text positions so era can be re-derived even
    when a chunk straddles two eras. Pure-python, deterministic, no LLM.
    """
    offsets = chunk_offsets or build_chunk_offsets(chunks) if chunks else {}
    store: Dict[str, Dict[str, Any]] = {}
    for item in pool:
        eid = str(item.get("evidence_id", "")).strip()
        if not eid:
            continue
        cid = str(item.get("chunk_id", ""))
        quote = str(item.get("quote", ""))
        chunk_text = chunks.get(cid, "")
        pos = chunk_text.find(quote) if quote else -1
        start = (offsets.get(cid, 0) + pos) if pos >= 0 else offsets.get(cid, 0)
        end = start + len(quote) if pos >= 0 else start
        # Re-derive era_id from spans when available
        era_id = str(item.get("era_id", ""))
        if era_spans and pos >= 0:
            for sp in era_spans:
                if sp.get("start", 0) <= start < sp.get("end", 0):
                    if sp.get("era_id"):
                        era_id = str(sp["era_id"])
                    break
        store[eid] = {
            "evidence_id": eid,
            "chunk_id": cid,
            "era": str(item.get("era", "")),
            "era_id": era_id,
            "type": str(item.get("type", "")),
            "signal": str(item.get("signal", "")),
            "text": quote,
            "start_offset": start,
            "end_offset": end,
        }
    return store


def resolve_evidence_ref(
    ref: str,
    evidence_store_ids: Dict[str, Dict[str, Any]],
) -> Tuple[bool, str]:
    """Check an LLM-cited evidence_id exists. Returns (ok, era_or_empty)."""
    unit = evidence_store_ids.get(str(ref).strip())
    if not unit:
        return False, ""
    return True, str(unit.get("era", ""))


# Evidence anchors may cite IDs only. The metric guess below is a *default*
# label for the expanded anchor; the analysis prompt tells the model to write
# its own metric, and this fallback only keeps the field parseable.
_ANCHOR_TYPE_METRIC = {
    "metaphor_anchor": "比喻密度",
    "dash_anchor": "破折号",
    "ellipsis_anchor": "省略号",
    "dialogue_tag_anchor": "对话占比",
    "short_para_anchor": "极短段率",
    "exemplification_anchor": "比喻密度",
}


def expand_evidence_refs(
    cards: Any,
    evidence_store_ids: Dict[str, Dict[str, Any]],
) -> int:
    """Expand ``evidence_refs`` (EID-only citations) into full evidence items.

    The prompt encourages ID-only citation, but schema counting, evidence
    verification and rendering all operate on ``evidence[]``. Expansion happens
    once, before any of those run, so a pure-ID card is not miscounted as
    "0 evidences". Existing items are never overwritten; the store is the
    authority for quote/chunk/era. Returns the number of items added.
    """
    if not isinstance(cards, list):
        return 0
    added = 0
    for card in cards:
        if not isinstance(card, dict):
            continue
        refs = card.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            continue
        evidence = card.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
            card["evidence"] = evidence
        for ref in refs:
            ref_id = str(ref).strip()
            if not ref_id:
                continue
            if any(isinstance(item, dict) and str(item.get("evidence_id", "")) == ref_id
                   for item in evidence):
                continue
            unit = evidence_store_ids.get(ref_id, {})
            evidence.append({
                "evidence_id": ref_id,
                "chunk_id": str(unit.get("chunk_id", "")),
                "quote": str(unit.get("text", "")),
                "metric": _ANCHOR_TYPE_METRIC.get(str(unit.get("type", "")), "比喻密度"),
                "note": "由 evidence_refs 展开（响应未提供证据正文）",
                "era": str(unit.get("era", "")),
                "era_id": str(unit.get("era_id", "")),
            })
            added += 1
    return added


def build_chunk_offsets(chunks: Dict[str, str]) -> Dict[str, int]:
    """Cumulative start offset of each chunk within the sampled text."""
    offsets: Dict[str, int] = {}
    cursor = 0
    for cid in sorted(chunks.keys()):
        offsets[cid] = cursor
        cursor += len(chunks[cid])
    return offsets


def derive_evidence_era(
    quote: str,
    chunk_id: str,
    chunks: Dict[str, str],
    era_map: Dict[str, str],
    era_spans: List[Dict[str, Any]],
    chunk_offsets: Dict[str, int],
) -> str:
    """按语料实测重推导证据所属时期，不信任 LLM 自报值。

    优先在 chunk 内定位原文的精确偏移，再落到覆盖该全局偏移的时期区间；
    找不到原文位置时退回 chunk 起点的 era_map 标签（chunk 可能跨越两个时期，
    起点标签会把后半段的引文标错时期）。
    """
    cid = str(chunk_id or "")
    text = chunks.get(cid, "")
    if quote and text:
        pos = text.find(quote)
        if pos >= 0 and era_spans:
            global_pos = chunk_offsets.get(cid, 0) + pos
            for span in era_spans:
                if span.get("start", 0) <= global_pos < span.get("end", 0):
                    return str(span.get("era", "")).strip()
    return str(era_map.get(cid, "")).strip()


# 引文回验最短门槛：任何 ≥6 字的原文片段才可能成为「已验证锚点」。
# 旧值 2 等于放行任意双字片段（如人名）冒充证据；这是模块常量，可回调。
MIN_QUOTE_CHARS = 6


def verify_evidence_item(
    quote: str,
    target_chunk_id: str,
    chunks: Dict[str, str],
) -> Tuple[str, str]:
    """
    Verify quote string against corpus chunks.
    Returns (status, resolved_chunk_id):
    - status: 'valid' | 'fixed' | 'downgraded'
    - resolved_chunk_id: corrected or original chunk_id
    """
    if not quote or len(quote.strip()) < MIN_QUOTE_CHARS:
        return ("downgraded", target_chunk_id)

    norm_quote = normalize_quote(quote)

    # 1. Exact or normalized check in target chunk
    if target_chunk_id and target_chunk_id in chunks:
        norm_chunk = normalize_quote(chunks[target_chunk_id])
        if norm_quote in norm_chunk or quote in chunks[target_chunk_id]:
            return ("valid", target_chunk_id)

    # 2. Search in all chunks to fix chunk_id
    for cid, ctext in chunks.items():
        norm_ctext = normalize_quote(ctext)
        if norm_quote in norm_ctext or quote in ctext:
            return ("fixed", cid)

    # Do not treat a partial clause as a verified quote. A generated report may
    # only claim an evidence anchor when the complete normalized quote is found.
    # Partial matches are intentionally downgraded for manual review.

    # 3. Not found in corpus
    return ("downgraded", target_chunk_id)


def verify_all_cards_evidence(
    cards_data: List[Dict[str, Any]],
    chunks: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Verify quotes across all technique cards and downgrade confidence if unverified.
    """
    stats = {"valid": 0, "fixed": 0, "downgraded": 0}
    verified_cards = []

    conf_downgrade_map = {
        "high": "mid",
        "mid": "low",
        "low": "low",
    }

    for card in cards_data:
        card_copy = dict(card)
        evidence_list = card_copy.get("evidence", [])
        updated_evidence = []
        has_downgrade = False

        for ev in evidence_list:
            if isinstance(ev, dict):
                cid = str(ev.get("chunk_id", ""))
                q = str(ev.get("quote", ""))
                status, fixed_cid = verify_evidence_item(q, cid, chunks)
                stats[status] += 1
                ev_copy = dict(ev)
                ev_copy["chunk_id"] = fixed_cid
                ev_copy["verification_status"] = status
                if status == "downgraded":
                    has_downgrade = True
                    # 复核提示放独立字段：metric 必须保持为可被
                    # metric_token_from_label 解析的合法指标名，污染该字段
                    # 会让公开 report.json 的下游机器读取失败。
                    ev_copy["review_note"] = "证据待复核（未在语料中命中）"
                updated_evidence.append(ev_copy)
            else:
                updated_evidence.append(ev)

        card_copy["evidence"] = updated_evidence
        if has_downgrade:
            current_conf = card_copy.get("confidence", "high").lower()
            card_copy["confidence"] = conf_downgrade_map.get(current_conf, "low")

        verified_cards.append(card_copy)

    return (verified_cards, stats)


# ---------------------------------------------------------------------------
# Definition <-> evidence reinforcement check
# ---------------------------------------------------------------------------
# When a card's name/definition promises a punctuation or dialogue/simile
# feature, its evidence quotes should physically contain that feature;
# otherwise the evidence is inference and confidence must drop one notch.
_FEATURE_PUNCT = {
    "省略号": "……",
    "破折号": "——",
    "感叹号": "！",
    "问号": "？",
}
_DIALOGUE_TERMS = ("对话", "对白", "标签", "说话人", "引语", "口吻")
_SIMILE_TERMS = ("比喻", "喻")
_QUOTE_CHAR_RE = re.compile(r"[“”「」『』\"']")
_TAG_VERB_RE = re.compile(r"(?:说道|问道|答道|笑道|说|道|问|答)")
_SIMILE_MARKER_RE = re.compile(r"(?:宛如|犹如|如同|仿佛|像|如|若)")


def enforce_evidence_reinforcement(cards_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Downgrade card confidence when no evidence quote actually contains the
    feature the card's definition promises. Returns the issue list; cards are
    mutated in place so the report JSON carries the calibrated confidence.
    """
    downgrade = {"high": "mid", "mid": "low", "low": "low"}
    issues: List[Dict[str, Any]] = []

    for card in cards_data:
        body = f"{card.get('name', '')} {card.get('definition', '')}"
        quotes = [str(e.get("quote", "")) for e in card.get("evidence", []) if isinstance(e, dict)]
        problems: List[str] = []

        for term, punc in _FEATURE_PUNCT.items():
            if term in body and quotes and not any(punc in q for q in quotes):
                problems.append(f"定义提及{term}，但证据引文均不含「{punc}」")

        if any(t in body for t in _DIALOGUE_TERMS) and quotes:
            has_dialogue = any(_QUOTE_CHAR_RE.search(q) or _TAG_VERB_RE.search(q) for q in quotes)
            if not has_dialogue:
                problems.append("定义提及对白/标签，但证据引文均不含引语或对话标签")

        if any(t in body for t in _SIMILE_TERMS) and quotes:
            if not any(_SIMILE_MARKER_RE.search(q) for q in quotes):
                problems.append("定义提及比喻，但证据引文均不含显式喻词")

        if problems:
            current_conf = str(card.get("confidence", "high")).lower()
            card["confidence"] = downgrade.get(current_conf, "low")
            issues.append({
                "id": card.get("id", "?"),
                "problems": problems,
                "confidence_after": card["confidence"],
            })

    return issues
