# -*- coding: utf-8 -*-
"""Claim-centric model: optional atomic style claims.

A Claim is the smallest verifiable style proposition:
  phenomenon + mechanism + effect + boundary + evidence + metrics + eras.

当前流水线的渲染真源是 ``technique_cards`` 与 ``thinking_layer``
（见 ``report/renderer.py`` 的 ``_compose_single_source``），Markdown 从 JSON
渲染；``claims`` 是**可选扩展层**——分析 Prompt 的 JSON 规范不要求产出它，
因此默认响应里 ``claims`` 为空数组。校验器只在响应确实带 ``claims`` 时
按本模块的严格规则核销 EID/MID 存在性（fail-closed），不带则跳过。

不要把本层描述成渲染真源：那与实现不符，会让调用方误以为报告已按 Claim
组织。若将来要把它提升为 SSOT，需要同时改 Prompt 契约、渲染器与本报告契约。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


VALID_CATEGORIES = {
    "rhythm", "syntax", "paragraph", "dialogue", "punctuation",
    "rhetoric", "perspective", "description", "imagery", "thinking",
}


@dataclass
class Claim:
    claim_id: str
    category: str
    statement: str
    mechanism: str = ""
    effect: str = ""
    boundary: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    metric_refs: List[str] = field(default_factory=list)
    era_refs: List[str] = field(default_factory=list)
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Claim":
        def _strlist(v: Any) -> List[str]:
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            return []
        try:
            conf = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        return cls(
            claim_id=str(data.get("claim_id", "")).strip(),
            category=str(data.get("category", "")).strip(),
            statement=str(data.get("statement", "")).strip(),
            mechanism=str(data.get("mechanism", "")).strip(),
            effect=str(data.get("effect", "")).strip(),
            boundary=str(data.get("boundary", "")).strip(),
            evidence_refs=_strlist(data.get("evidence_refs")),
            metric_refs=_strlist(data.get("metric_refs")),
            era_refs=_strlist(data.get("era_refs")),
            confidence=conf,
        )

    def validate(self) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        if not self.claim_id:
            errors.append("claim_id cannot be empty")
        if self.category not in VALID_CATEGORIES:
            errors.append(
                f"Claim {self.claim_id or '?'}: category must be one of "
                f"{sorted(VALID_CATEGORIES)}, got '{self.category}'")
        if not self.statement:
            errors.append(f"Claim {self.claim_id or '?'}: statement cannot be empty")
        if not self.evidence_refs:
            errors.append(f"Claim {self.claim_id or '?'}: evidence_refs cannot be empty")
        if not (0.0 <= self.confidence <= 1.0):
            errors.append(
                f"Claim {self.claim_id or '?'}: confidence must be 0..1, got {self.confidence}")
        return (len(errors) == 0, errors)


def validate_claims(
    claims_raw: Any,
    evidence_store_ids: Dict[str, Any],
    metric_registry: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """Validate claim list against trusted stores.

    Returns (normalized_claims, errors, warnings). Unknown EID/MID are errors
    (fail-closed). Category/era typos are errors. Missing mechanism/effect/
    boundary degrade to warnings (quality signal, not integrity block).
    """
    errors: List[str] = []
    warnings: List[str] = []
    if claims_raw is None:
        return [], [], []
    if not isinstance(claims_raw, list):
        return [], ["claims must be a list"], []
    seen: set = set()
    normalized: List[Dict[str, Any]] = []
    for idx, raw in enumerate(claims_raw):
        if not isinstance(raw, dict):
            errors.append(f"claims[{idx}] must be an object")
            continue
        claim = Claim.from_dict(raw)
        ok, errs = claim.validate()
        if not ok:
            errors.extend(errs)
        cid = claim.claim_id or f"CL{idx:03d}"
        if cid in seen:
            errors.append(f"claims: duplicate claim_id '{cid}'")
        seen.add(cid)
        for eid in claim.evidence_refs:
            if eid not in (evidence_store_ids or {}):
                errors.append(f"Claim {cid}: 未知证据ID {eid}")
        for mid in claim.metric_refs:
            if mid not in (metric_registry or {}):
                # allow token alias form (e.g. avg_sent_len for M010)
                try:
                    from ..report.metrics import _TOKEN_TO_MID as _t2m
                    if _t2m.get(mid) not in (metric_registry or {}):
                        errors.append(f"Claim {cid}: 未知指标ID {mid}")
                except Exception:
                    errors.append(f"Claim {cid}: 未知指标ID {mid}")
        if not claim.mechanism or not claim.effect or not claim.boundary:
            warnings.append(
                f"Claim {cid}: 现象/机制/效果/边界不完整,质量降级")
        normalized.append({
            "claim_id": cid,
            "category": claim.category,
            "statement": claim.statement,
            "mechanism": claim.mechanism,
            "effect": claim.effect,
            "boundary": claim.boundary,
            "evidence_refs": claim.evidence_refs,
            "metric_refs": claim.metric_refs,
            "era_refs": claim.era_refs,
            "confidence": claim.confidence,
        })
    return normalized, errors, warnings
