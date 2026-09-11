# -*- coding: utf-8 -*-
"""Quality self-assessment for the delivered report.

Separate from integrity: a report can satisfy every hard contract (schema,
evidence, privacy, numerics) and still be shallow. The assessment is therefore
*non-blocking* — it never changes ``status``; it drives ``publishable`` and the
``quality`` block that a caller (or the CLI) uses to decide whether to rework.

Thresholds mirror ``references/quality-baseline.md`` so the human-readable bar
and the machine check cannot drift apart.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: A section body at/above this is a full causal-diagnosis paragraph.
SECTION_FULL_CHARS = 120
#: Below this the section is a stub.
SECTION_PARTIAL_CHARS = 60
#: 1.9-1.11 are diagnosis sections too; the analysis prompt promises >=80 chars
#: of mechanism reasoning, so they are held to that floor.
QUALITATIVE_MIN_CHARS = 80
QUALITATIVE_SECTIONS = ("1.9", "1.10", "1.11")
#: Share of 1.11 style-marker lines that must carry a data anchor.
STYLE_MARKER_MIN_RATIO = 0.5
#: Long-arc prose must cite at least this many distinct era anchors.
MIN_LONG_ARC_ANCHORS = 2

_SECTION_HEADING_RE = re.compile(r"^###\s+1\.(\d+)\b[^\n]*\n", re.M)
_ANCHOR_RE = re.compile(r"\[(c[0-9a-zA-Z_-]+)\]")


def _section_bodies(prose_markdown: str) -> Dict[str, str]:
    bodies: Dict[str, str] = {}
    matches = list(_SECTION_HEADING_RE.finditer(prose_markdown))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(prose_markdown)
        bodies[f"1.{match.group(1)}"] = prose_markdown[match.end():end].strip()
    return bodies


def _style_marker_support(prose_markdown: str) -> Dict[str, Any]:
    """Share of 1.11 lines that cite a number or placeholder.

    Heading lines are excluded from the denominator: they are structure, not
    diagnosis, and counting them once pulled compliant responses under the
    threshold (e.g. 3/7=0.43) while pointing at the wrong root cause.
    """
    section = re.search(r"^###\s+1\.11\b[^\n]*\n(.*?)(?=^#{2,4}\s|\Z)", prose_markdown, re.M | re.S)
    if not section:
        return {"ratio": None, "supported": 0, "total": 0}
    lines = [
        line for line in section.group(1).splitlines()
        if line.strip() and not re.match(r"^#{1,4}\s", line)
    ]
    total = len(lines)
    supported = sum(1 for line in lines if re.search(r"\d|\{\{", line))
    return {
        "ratio": round(supported / total, 2) if total else None,
        "supported": supported,
        "total": total,
        "unsupported_lines": [
            {"line": index + 1, "preview": line.strip()[:40]}
            for index, line in enumerate(lines)
            if not re.search(r"\d|\{\{", line)
        ],
    }


def _long_arc_status(
    parsed_json: Dict[str, Any],
    prepare_result: Optional[Dict[str, Any]],
) -> Tuple[List[str], List[str], str]:
    thinking = parsed_json.get("thinking_layer") or {}
    long_arc = str(thinking.get("long_arc", ""))
    anchors = sorted(set(_ANCHOR_RE.findall(long_arc)))

    anchor_eras: List[str] = []
    if prepare_result and anchors:
        evidence_store = prepare_result.get("evidence_store") or {}
        era_map = prepare_result.get("era_map") or {}
        era_spans = prepare_result.get("era_spans") or []
        if evidence_store:
            from ..distill.evidence import build_chunk_offsets, derive_evidence_era

            chunk_offsets = prepare_result.get("chunk_offsets") or build_chunk_offsets(evidence_store)
            for chunk_id in anchors:
                anchor_eras.append(
                    derive_evidence_era("", chunk_id, evidence_store, era_map, era_spans, chunk_offsets)
                )
    valid_eras = sorted({era for era in anchor_eras if era and era != "未分期"})
    if len(valid_eras) >= 2:
        status = "cross_era_ok"
    elif len(anchors) >= MIN_LONG_ARC_ANCHORS:
        status = "ok"
    else:
        status = "weak"
    return anchors, valid_eras, status


def assess_quality(
    prose_markdown: str,
    parsed_json: Dict[str, Any],
    prepare_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect the depth signals the quality gate judges."""
    bodies = _section_bodies(prose_markdown or "")
    section_scores = {
        name: ("full" if len(body) >= SECTION_FULL_CHARS
               else ("partial" if len(body) >= SECTION_PARTIAL_CHARS else "low"))
        for name, body in bodies.items()
    }
    anchors, anchor_eras, long_arc_status = _long_arc_status(parsed_json or {}, prepare_result)
    return {
        "section_scores": section_scores,
        "section_lengths": {name: len(body) for name, body in bodies.items()},
        "long_arc_anchors": anchors,
        "long_arc_anchor_eras": anchor_eras,
        "long_arc_status": long_arc_status,
        "style_marker_support": _style_marker_support(prose_markdown or ""),
    }


def assess_quality_gate(quality: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Turn quality signals into (status, blocking reasons).

    Lenient by design: only stub sections, an unsupported long-arc claim, a
    weakly-anchored style-marker list, and under-length qualitative sections
    fail. Partial-length diagnosis sections are reported as notes, because the
    runtime contract only enforces non-empty bodies.
    """
    reasons: List[str] = []
    scores = quality.get("section_scores") or {}
    if not scores:
        return "passed", ["无可评估小节（空正文或测试夹具）"]

    lows = sorted(name for name, score in scores.items() if score == "low")
    if lows:
        reasons.append(f"诊断深度不足的小节: {','.join(lows)} (<{SECTION_PARTIAL_CHARS}字)")

    lengths = quality.get("section_lengths") or {}
    short_qualitative = [
        name for name in QUALITATIVE_SECTIONS
        if name in lengths and lengths[name] < QUALITATIVE_MIN_CHARS
    ]
    if short_qualitative:
        reasons.append(
            f"定性小节机制诊断不足: {','.join(short_qualitative)} (<{QUALITATIVE_MIN_CHARS}字)"
        )

    if quality.get("long_arc_status") == "weak":
        reasons.append(f"长线布局缺少>={MIN_LONG_ARC_ANCHORS}组锚点引用")

    support = quality.get("style_marker_support") or {}
    ratio = support.get("ratio")
    if isinstance(ratio, float) and support.get("total", 0) >= 3 and ratio < STYLE_MARKER_MIN_RATIO:
        detail = "; ".join(
            f"§1.11 第{item.get('line')}行「{item.get('preview', '')}」"
            for item in (support.get("unsupported_lines") or [])[:3]
        )
        reasons.append(
            f"风格标记数据支撑率低: {support.get('supported')}/{support.get('total')}={ratio}"
            + (f"，未含数据依据的行: {detail}" if detail else "")
        )
    return ("failed" if reasons else "passed"), reasons


def quality_notes(quality: Dict[str, Any]) -> List[str]:
    """Non-blocking observations (kept separate from gate reasons)."""
    scores = quality.get("section_scores") or {}
    partial = sorted(name for name, score in scores.items() if score == "partial")
    if not partial:
        return []
    return [
        f"小节篇幅未达完整诊断段标准（{SECTION_PARTIAL_CHARS}-{SECTION_FULL_CHARS}字）: "
        + ",".join(partial)
    ]
