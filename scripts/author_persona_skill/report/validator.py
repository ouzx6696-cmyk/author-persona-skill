# -*- coding: utf-8 -*-
"""Report validator: schema + evidence + privacy + numeric audit.

Four independent gates run against one response; each returns its own status so
the caller can say *what* failed. Only ``schema`` / ``desensitization`` /
``numeric_audit`` are blocking; evidence shortfalls and quality findings surface
through their own keys.

Design notes that are load-bearing:

* ``expand_evidence_refs`` runs first, so an ID-only card is not counted as
  "0 evidences" by the schema pass.
* Evidence eras are re-derived from the corpus; a declared era is only reported
  as a warning before being overwritten, otherwise one chunk could be dressed
  up as two eras and defeat the cross-era gate.
* A downgraded quote stays visible for review but cannot satisfy the evidence
  minimum.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..distill.technique_cards import TechniqueCard, check_card_content_quality
from ..distill.thinking_layer import ThinkingLayer
from ..distill.desensitize import (
    COMMON_WHITELIST,
    validate_desensitization,
    validate_desensitization_json,
    validate_desensitization_map,
)
from ..distill.evidence import (
    build_chunk_offsets,
    derive_evidence_era,
    enforce_evidence_reinforcement,
    expand_evidence_refs,
    verify_all_cards_evidence,
)
from .metrics import (
    audit_json_numeric_claims,
    audit_numeric_claims,
    build_metric_registry,
    build_placeholder_map,
    metric_token_present,
    substitute_placeholders,
)
from .quality import assess_quality, assess_quality_gate, quality_notes

MIN_CARDS = 3
MAX_CARDS = 6
MIN_EVIDENCE = 2

#: Top-level JSON keys the machine block may carry. Unknown roots are rejected:
#: the block is a public API contract, so silently ignoring stray fields would
#: let a malformed response look valid.
ALLOWED_ROOT_KEYS = frozenset({
    "writer_contract", "technique_cards", "thinking_layer",
    "desensitization_map", "dialogue_review", "claims",
    "evidence_refs", "metric_refs",
})


def validate_report(
    prose_markdown: str,
    parsed_json: Optional[Dict[str, Any]],
    prepare_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the four gates and return a machine-readable validation record."""
    errors: List[str] = []
    warnings: List[str] = []
    meta = prepare_result.get("prepare_meta", {})
    evidence_store = prepare_result.get("evidence_store", {})
    proper_noun_candidates = prepare_result.get("proper_noun_candidates", [])
    author_name = meta.get("author_name", "")
    work_title = meta.get("work_title", "")
    evidence_store_ids = prepare_result.get("evidence_store_ids") or {}
    quant = prepare_result.get("quantitative_features", {})

    schema_passed = True
    evidence_stats: Dict[str, Any] = {
        "valid": 0, "fixed": 0, "downgraded": 0,
        "cards_failed": [], "cross_era_status": "not_applicable",
    }
    verified_cards_data: List[Dict[str, Any]] = []
    cards_raw: List[Dict[str, Any]] = []

    if not parsed_json:
        schema_passed = False
        errors.append("LLM 响应未包含可解析的末尾 JSON 机器数据块。")
    else:
        cards_raw = parsed_json.get("technique_cards", [])
        if not isinstance(cards_raw, list):
            cards_raw = []
        # ID-only citations become full evidence items before any counting.
        expand_evidence_refs(cards_raw, evidence_store_ids)
        metric_registry = prepare_result.get("metric_registry") or build_metric_registry(quant)

        schema_passed = _check_cards(cards_raw, quant, metric_registry, errors, warnings) and schema_passed
        schema_passed = _check_thinking_layer(parsed_json, errors) and schema_passed
        schema_passed = _check_claims(parsed_json, prepare_result, errors, warnings) and schema_passed
        schema_passed = _check_writer_contract(parsed_json, errors) and schema_passed
        schema_passed = _check_dialogue_review(
            parsed_json, prepare_result, errors, warnings) and schema_passed

        for key in list(parsed_json.keys()):
            if key not in ALLOWED_ROOT_KEYS:
                schema_passed = False
                errors.append(f"JSON 顶层含非法字段：{key}")
                break

        verified_cards_data, evidence_stats = _verify_evidence(
            cards_raw, parsed_json, prepare_result, evidence_store, evidence_store_ids,
            errors, warnings, meta,
        )
        schema_passed = _check_evidence_minimum(
            verified_cards_data, evidence_stats, errors) and schema_passed

    desens_passed, desens_leaks = _check_privacy(
        prose_markdown, parsed_json, prepare_result, proper_noun_candidates,
        author_name, work_title, errors, warnings,
    )

    numeric_passed, numeric_conflicts = _check_numerics(prose_markdown, parsed_json, quant, errors, warnings)

    overall_status = (
        "passed" if (schema_passed and desens_passed and numeric_passed and not errors) else "failed"
    )
    quality_info = assess_quality(prose_markdown, parsed_json or {}, prepare_result)
    quality_status, quality_reasons = assess_quality_gate(quality_info)
    integrity_passed = schema_passed and numeric_passed
    publishable = (
        "passed" if (integrity_passed and desens_passed
                     and quality_status == "passed" and not errors) else "failed"
    )

    return {
        "status": overall_status,
        "schema": "passed" if schema_passed else "failed",
        "desensitization": "passed" if desens_passed else "failed",
        "numeric_audit": {
            "status": "passed" if numeric_passed else "failed",
            "conflicts": numeric_conflicts,
        },
        "evidence": evidence_stats,
        "quality": {
            **quality_info,
            "status": quality_status,
            "reasons": quality_reasons,
            "notes": quality_notes(quality_info),
        },
        "integrity": "passed" if integrity_passed else "failed",
        "quality_status": quality_status,
        "privacy": "passed" if desens_passed else "failed",
        "publishable": publishable,
        "desensitization_leaks": desens_leaks,
        "warnings": warnings,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Schema gate
# ---------------------------------------------------------------------------

def _check_cards(
    cards_raw: List[Any],
    quant: Dict[str, Any],
    metric_registry: Dict[str, Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
) -> bool:
    """Card-level schema, content gate, metric-label resolution, MID references."""
    if not isinstance(cards_raw, list) or not (MIN_CARDS <= len(cards_raw) <= MAX_CARDS):
        count = len(cards_raw) if isinstance(cards_raw, list) else 0
        errors.append(f"技法卡数量必须在 {MIN_CARDS}-{MAX_CARDS} 张之间，实际 {count} 张")
        return False

    passed = True
    seen_ids = set()
    for index, card_dict in enumerate(cards_raw):
        if not isinstance(card_dict, dict):
            passed = False
            errors.append(f"技法卡 [{index}] 必须是 JSON 对象")
            continue
        card_id = str(card_dict.get("id", "")).strip()
        if card_id in seen_ids:
            passed = False
            errors.append(f"技法卡 [{index}] 重复使用了 id '{card_id}'")
        seen_ids.add(card_id)

        try:
            card = TechniqueCard.from_dict(card_dict)
            ok, card_errors = card.validate(min_evidence=MIN_EVIDENCE)
            if not ok:
                passed = False
                errors.extend(card_errors)
        except Exception as exc:  # noqa: BLE001 - a broken card is a schema failure
            passed = False
            errors.append(f"技法卡 [{index}] 解析失败：{exc}")

        quality_errors, quality_warnings = check_card_content_quality(card_dict)
        if quality_errors:
            passed = False
            errors.extend(quality_errors)
        if any("置信度降级" in w for w in quality_warnings):
            current = str(card_dict.get("confidence", "high")).lower()
            card_dict["confidence"] = {"high": "mid", "mid": "low", "low": "low"}.get(current, "low")
        warnings.extend(quality_warnings)

        for ev_index, evidence_item in enumerate(card_dict.get("evidence") or []):
            if not isinstance(evidence_item, dict):
                continue
            label = str(evidence_item.get("metric", "")).strip()
            if label and not metric_token_present(label, quant):
                passed = False
                errors.append(
                    f"技法卡 {card_id or '?'}: 证据[{ev_index}] 的 metric 未出现在本次实测量化结果中：{label}"
                )
        passed = _check_metric_refs(card_dict, card_id, metric_registry, errors) and passed
    return passed


def _check_metric_refs(
    card_dict: Dict[str, Any],
    card_id: str,
    metric_registry: Dict[str, Dict[str, Any]],
    errors: List[str],
) -> bool:
    from .metrics import _TOKEN_TO_MID

    passed = True
    for key in ("metric_refs", "metric_ids"):
        refs = card_dict.get(key)
        if not isinstance(refs, list):
            continue
        for ref in refs:
            text = str(ref).strip()
            if text and text not in metric_registry and _TOKEN_TO_MID.get(text) not in metric_registry:
                passed = False
                errors.append(f"技法卡 {card_id or '?'}: 引用的指标ID不存在：{text}")
    return passed


def _check_thinking_layer(parsed_json: Dict[str, Any], errors: List[str]) -> bool:
    thinking_raw = parsed_json.get("thinking_layer", {})
    if not isinstance(thinking_raw, dict):
        errors.append("thinking_layer 必须是包含 7 个维度的 JSON 对象。")
        return False
    ok, thinking_errors = ThinkingLayer.from_dict(thinking_raw).validate()
    if not ok:
        errors.extend(thinking_errors)
    return ok


def _check_claims(parsed_json: Dict[str, Any], prepare_result: Dict[str, Any],
                  errors: List[str], warnings: List[str]) -> bool:
    """Claims are an optional extension layer; strict only when present."""
    if not isinstance(parsed_json.get("claims"), list):
        return True
    try:
        from ..distill.claims import validate_claims

        registry = prepare_result.get("metric_registry") or build_metric_registry(
            prepare_result.get("quantitative_features", {}) or {})
        normalized, claim_errors, claim_warnings = validate_claims(
            parsed_json.get("claims"),
            prepare_result.get("evidence_store_ids") or {},
            registry,
        )
        if claim_errors:
            errors.extend(claim_errors)
        warnings.extend(claim_warnings)
        parsed_json["claims"] = normalized
        return not claim_errors
    except Exception as exc:  # noqa: BLE001 - malformed claims are a schema failure
        errors.append(f"claims 校验异常：{exc}")
        return False


def _check_writer_contract(parsed_json: Dict[str, Any], errors: List[str]) -> bool:
    from ..distill.writer_contract import WriterContract

    contract_raw = parsed_json.get("writer_contract")
    if not isinstance(contract_raw, dict):
        errors.append("JSON 缺少 writer_contract（第〇部分：作家定义与读者契约），无法渲染四层报告。")
        return False
    ok, contract_errors = WriterContract.from_dict(contract_raw).validate()
    if not ok:
        errors.extend(contract_errors)
    return ok


#: 语料实测到多少个高置信说话人以上时，就要求 dialogue_review 至少确认一个原型。
#: 单人语料（一个说话人）不强制：那更像集中式对白，不该逼模型编出第二个人格。
_DIALOGUE_REVIEW_MIN_SPEAKERS = 2


def _check_dialogue_review(
    parsed_json: Dict[str, Any],
    prepare_result: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> bool:
    """Gate the 1.9 角色话术复盘块.

    该槽位此前只有契约没有校验：模型可以给出口吻结论却不对应任何实测说话人，
    也可以把角色名当 role 写回来（绕过脱敏）。三道检查——角色数、tone 非空、
    标签可解析——正是为了堵这两个口子。
    """
    review = parsed_json.get("dialogue_review")
    if not isinstance(review, dict):
        errors.append("JSON 缺少 dialogue_review（1.9 角色话术复盘），无法核对原型口吻的实测来源。")
        return False

    profiles = review.get("confirmed_profiles")
    discarded = review.get("discarded_candidates")
    if not isinstance(profiles, list):
        errors.append("dialogue_review.confirmed_profiles 必须是列表。")
        return False
    if discarded is not None and not isinstance(discarded, list):
        errors.append("dialogue_review.discarded_candidates 必须是列表。")
        return False

    measured = (prepare_result.get("quantitative_features", {}) or {}).get(
        "dialogue_features", {}).get("high_confidence_speakers", [])
    measured_count = len(measured) if isinstance(measured, list) else 0

    # 可解析标签 = 公开映射的替换值。_build_public_mapping 是渲染公开产物时的同
    # 一个函数，复用它才能保证「校验通过的标签」就是「渲染后会出现的标签」。
    from .renderer import _build_public_mapping
    desens_map = parsed_json.get("desensitization_map", {})
    public_mapping, _map_errors, _map_warnings = _build_public_mapping(
        desens_map, prepare_result.get("proper_noun_candidates", []) or [])
    valid_labels = set(public_mapping.values())

    ok = True
    seen_roles: List[str] = []
    for idx, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            errors.append(f"dialogue_review.confirmed_profiles[{idx}] 必须是对象。")
            ok = False
            continue
        role = str(profile.get("role", "")).strip()
        tone = str(profile.get("tone", "")).strip()
        sample_tag = str(profile.get("sample_tag", "")).strip()
        if len(role) < 2:
            errors.append(f"dialogue_review.confirmed_profiles[{idx}].role 缺失或过短，无法定位原型。")
            ok = False
        elif valid_labels and role not in valid_labels:
            errors.append(
                f"dialogue_review.confirmed_profiles[{idx}].role「{role}」不是脱敏映射给出的原型标签，"
                "禁止使用映射之外的名字（硬约束清单 #6）。")
            ok = False
        if len(tone) < 2:
            errors.append(f"dialogue_review.confirmed_profiles[{idx}].tone 不能为空：口吻结论必须写明。")
            ok = False
        if not sample_tag:
            errors.append(f"dialogue_review.confirmed_profiles[{idx}].sample_tag 不能为空。")
            ok = False
        if role and role in seen_roles:
            warnings.append(f"dialogue_review 中原型「{role}」重复确认，已按首条为准。")
        elif role:
            seen_roles.append(role)

    if not profiles and measured_count >= _DIALOGUE_REVIEW_MIN_SPEAKERS:
        errors.append(
            f"语料实测有 {measured_count} 名高置信说话人，但 dialogue_review.confirmed_profiles 为空："
            "角色话术必须由实测支撑，不允许留空（1.9 节将无锚点）。")
        ok = False
    elif profiles and measured_count and len(profiles) > measured_count:
        warnings.append(
            f"dialogue_review 确认了 {len(profiles)} 个原型，超过实测高置信说话人 {measured_count} 名。")
    return ok

# ---------------------------------------------------------------------------
# Evidence gate
# ---------------------------------------------------------------------------

def _verify_evidence(
    cards_raw: List[Any],
    parsed_json: Dict[str, Any],
    prepare_result: Dict[str, Any],
    evidence_store: Dict[str, str],
    evidence_store_ids: Dict[str, Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
    meta: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "valid": 0, "fixed": 0, "downgraded": 0,
        "cards_failed": [], "cross_era_status": "not_applicable",
    }
    if not isinstance(cards_raw, list) or not evidence_store:
        return [], stats

    # EID existence gate before fuzzy matching: an ID that is not in the
    # trusted store is fail-closed (anti-hallucination + anti-injection).
    for card in cards_raw:
        if not isinstance(card, dict):
            continue
        for ev in card.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            eid = str(ev.get("evidence_id", "")).strip()
            if not eid:
                continue
            unit = evidence_store_ids.get(eid)
            if unit is None:
                errors.append(f"技法卡 {card.get('id', '?')}: 引用的证据ID不存在：{eid}")
                continue
            # Snap chunk/era to trusted values; the model's self-report is ignored.
            ev["chunk_id"] = str(unit.get("chunk_id", ev.get("chunk_id", "")))
            if unit.get("era"):
                ev["era"] = str(unit["era"])
            if unit.get("era_id"):
                ev["era_id"] = str(unit["era_id"])
            if not str(ev.get("quote", "")).strip():
                ev["quote"] = str(unit.get("text", ""))

    verified_cards_data, verified_stats = verify_all_cards_evidence(cards_raw, evidence_store)
    for key in ("valid", "fixed", "downgraded"):
        stats[key] = verified_stats.get(key, 0)

    era_map = prepare_result.get("era_map", {}) or {}
    era_spans = prepare_result.get("era_spans") or []
    chunk_offsets = prepare_result.get("chunk_offsets") or build_chunk_offsets(evidence_store)

    for card in verified_cards_data:
        for ev in card.get("evidence", []):
            if not isinstance(ev, dict):
                continue
            derived = derive_evidence_era(
                str(ev.get("quote", "")), str(ev.get("chunk_id", "")),
                evidence_store, era_map, era_spans, chunk_offsets,
            )
            declared = str(ev.get("era", "")).strip()
            if declared and derived and declared != derived:
                warnings.append(
                    f"技法卡 {card.get('id', '?')}: 证据自报时期 {declared} 与实测 {derived} 不符，已按实测修正"
                )
            if derived:
                ev["era"] = derived
                try:
                    from ..corpus.reading_plan import era_id_for_label
                    era_id = era_id_for_label(derived)
                    if era_id:
                        ev["era_id"] = era_id
                except Exception:  # noqa: BLE001 - era_id is a convenience key
                    pass
    parsed_json["technique_cards"] = verified_cards_data

    for issue in enforce_evidence_reinforcement(verified_cards_data):
        warnings.append(
            f"技法卡 {issue['id']}: 证据与定义要素不一致，置信降级为 {issue['confidence_after']}："
            + "；".join(issue["problems"])
        )
    stats["cross_era_status"] = _cross_era_status(
        verified_cards_data, era_map, meta, stats, errors, warnings)
    return verified_cards_data, stats


def _cross_era_status(
    verified_cards_data: List[Dict[str, Any]],
    era_map: Dict[str, str],
    meta: Dict[str, Any],
    stats: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> str:
    """Require at least one card to hold two strictly verified eras itself."""
    available_eras = {
        str(v).strip() for v in era_map.values() if str(v).strip() and str(v) != "未分期"
    }
    if meta.get("is_fallback_index", False):
        warnings.append("语料未识别出真实章节（fallback 分段），跨时期证据校验不适用")
        return "not_applicable"
    if len(available_eras) < 2:
        warnings.append("采样未形成至少两个可识别时期，跨时期证据校验不适用")
        return "not_applicable"

    cross_era_cards = []
    for card in verified_cards_data:
        card_eras = {
            str(ev.get("era", "")).strip()
            for ev in card.get("evidence", [])
            if isinstance(ev, dict)
            and ev.get("verification_status") in {"valid", "fixed"}
            and str(ev.get("era", "")).strip()
            and str(ev.get("era", "")).strip() != "未分期"
        }
        if len(card_eras) >= 2:
            cross_era_cards.append(str(card.get("id", "?")))
    if cross_era_cards:
        stats["cross_era_cards"] = cross_era_cards
        return "passed"
    errors.append("至少一张技法卡需要提供两个不同时期的严格命中证据（按卡校验）")
    return "failed"


def _check_evidence_minimum(
    verified_cards_data: List[Dict[str, Any]],
    stats: Dict[str, Any],
    errors: List[str],
) -> bool:
    """A card needs enough strictly verified anchors; downgrades do not count."""
    if not verified_cards_data:
        return True
    passed = True
    for card in verified_cards_data:
        evidence_items = card.get("evidence", []) if isinstance(card, dict) else []
        usable = [
            ev for ev in evidence_items
            if isinstance(ev, dict) and ev.get("verification_status") in {"valid", "fixed"}
        ]
        if len(usable) < MIN_EVIDENCE:
            passed = False
            card_id = str(card.get("id", "?"))
            stats.setdefault("cards_failed", []).append(card_id)
            errors.append(
                f"技法卡 {card_id}: 严格命中的证据不足（需要 {MIN_EVIDENCE} 条，实际 {len(usable)} 条，"
                f"硬约束清单 #2：请改引候选证据池中 6–80 字的其他锚点）"
            )
    return passed


# ---------------------------------------------------------------------------
# Privacy gate
# ---------------------------------------------------------------------------

def _check_privacy(
    prose_markdown: str,
    parsed_json: Optional[Dict[str, Any]],
    prepare_result: Dict[str, Any],
    proper_noun_candidates: List[Dict[str, Any]],
    author_name: str,
    work_title: str,
    errors: List[str],
    warnings: List[str],
) -> Tuple[bool, List[Dict[str, Any]]]:
    passed = True
    leaks: List[Dict[str, Any]] = []
    if not prepare_result.get("prepare_meta", {}).get("desensitize", True):
        return True, []

    desens_map = parsed_json.get("desensitization_map", {}) if parsed_json else {}
    map_errors, map_warnings = validate_desensitization_map(desens_map, proper_noun_candidates)
    if map_errors:
        passed = False
        errors.extend(f"脱敏映射错误：{issue.get('reason', issue)}" for issue in map_errors)
    warnings.extend(f"脱敏映射提示：{issue.get('reason', issue)}" for issue in map_warnings)

    body_to_verify = prose_markdown
    if desens_map:
        from .renderer import desensitize_prose
        body_to_verify = desensitize_prose(prose_markdown, desens_map)

    body_passed, leaks = validate_desensitization(
        report_body=body_to_verify,
        proper_noun_candidates=proper_noun_candidates,
        author_name=author_name,
        work_title=work_title,
    )
    passed = passed and body_passed
    errors.extend(f"脱敏泄露检测：{leak['reason']}（硬约束清单 #6）" for leak in leaks)

    structured_leaks = validate_desensitization_json(
        parsed_json or {}, proper_noun_candidates, author_name=author_name, work_title=work_title)
    if structured_leaks:
        passed = False
        leaks.extend(structured_leaks)
        errors.extend(f"脱敏泄露检测：{leak['reason']}（硬约束清单 #6）" for leak in structured_leaks)

    for item in proper_noun_candidates:
        term = item.get("term", "")
        score = item.get("score", 0)
        if (score >= 10 and len(term) >= 2 and term != author_name
                and term not in COMMON_WHITELIST and term not in desens_map):
            warnings.append(
                f"脱敏映射缺少高频专名 '{term}' (score={score})，请补充原型标签或确认其属通用词")
    return passed, leaks


# ---------------------------------------------------------------------------
# Numeric gate
# ---------------------------------------------------------------------------

def _check_numerics(
    prose_markdown: str,
    parsed_json: Optional[Dict[str, Any]],
    quant: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> Tuple[bool, List[Dict[str, str]]]:
    """Core-metric contradictions block; minor ones warn.

    Prose and JSON structure fields are audited separately but share one
    placeholder registry, so a number cannot be right in one channel and wrong
    in the other.
    """
    if not quant:
        return True, []
    placeholder_map = build_placeholder_map(quant)
    audited_prose = substitute_placeholders(prose_markdown, placeholder_map)
    conflicts = audit_numeric_claims(audited_prose, quant, placeholder_map)
    conflicts.extend(audit_json_numeric_claims(parsed_json or {}, quant, placeholder_map))
    hard = [c for c in conflicts if c.get("severity") == "error"]
    soft = [c for c in conflicts if c.get("severity") != "error"]
    for conflict in hard[:10]:
        errors.append(
            f"数值审计冲突 [{conflict['token']}]: 报告写 {conflict['written']}，"
            f"实测 {conflict['measured']}；上下文：{conflict['context']}"
        )
    for conflict in soft[:10]:
        warnings.append(
            f"数值偏差提示 [{conflict['token']}]: 报告写 {conflict['written']}，"
            f"实测 {conflict['measured']}（非核心指标，仅提示）"
        )
    return not hard, conflicts
