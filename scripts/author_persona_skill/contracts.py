# -*- coding: utf-8 -*-
"""Stage contract between ``prepare_analysis`` and ``finalize_analysis``.

The three-step workflow hands one large dictionary from stage 1 to stage 3 —
possibly through a file on disk, possibly across a version upgrade. This module
is the single declaration of what that hand-off must contain, so a malformed or
stale ``prepare_result`` fails with an actionable message instead of a KeyError
deep inside the renderer.

``PREPARE_SCHEMA_VERSION`` is bumped only when the hand-off *breaks* (a key is
removed or its meaning changes). Adding new keys is backward compatible: older
``prepare`` output keeps working, newer output exposes more.
"""
from __future__ import annotations

from typing import Any, Dict, List

#: Version of the prepare -> finalize hand-off. Independent of the report
#: ``schema_version`` (which describes the delivered artifacts, not the stage
#: contract) and of the package version.
PREPARE_SCHEMA_VERSION = "1"

#: Keys ``finalize_analysis`` reads directly.
REQUIRED_PREPARE_KEYS = (
    "llm_prompt",
    "llm_system_msg",
    "evidence_store",
    "evidence_store_ids",
    "era_map",
    "era_spans",
    "quantitative_features",
    "metric_registry",
    "placeholder_map",
    "proper_noun_candidates",
    "prepare_meta",
)

#: Keys read from ``prepare_meta``.
REQUIRED_META_KEYS = (
    "work_title",
    "desensitize",
    "allow_author_identity",
    "generate_system_prompt",
    "include_raw_evidence",
)

#: Optional keys that enrich the hand-off; absent values degrade gracefully.
OPTIONAL_PREPARE_KEYS = (
    "chunk_offsets",
    "era_id_map",
    "era_excerpts",
    "era_ranges",
    "era_window_metrics",
    "evidence_pool",
)


def validate_prepare_result(prepare_result: Any) -> List[str]:
    """Return a list of blocking contract violations (empty means usable).

    Deliberately narrow: it checks presence and container shape, not the
    correctness of the values — the validators own that.
    """
    errors: List[str] = []
    if not isinstance(prepare_result, dict):
        return [f"prepare_result 必须是字典，实际为 {type(prepare_result).__name__}"]

    for key in REQUIRED_PREPARE_KEYS:
        if key not in prepare_result:
            errors.append(f"prepare_result 缺少必需字段：{key}")

    meta = prepare_result.get("prepare_meta")
    if not isinstance(meta, dict):
        errors.append("prepare_result['prepare_meta'] 必须是字典")
    else:
        for key in REQUIRED_META_KEYS:
            if key not in meta:
                errors.append(f"prepare_meta 缺少必需字段：{key}")
        declared = meta.get("prepare_schema_version")
        if declared is None:
            errors.append(
                "prepare_meta 缺少 prepare_schema_version（请用同一版本重新运行 prepare_analysis）"
            )
        elif str(declared) != PREPARE_SCHEMA_VERSION:
            errors.append(
                f"prepare 阶段契约版本为 {declared}，本版本 finalize 需要 "
                f"{PREPARE_SCHEMA_VERSION}；请重新运行 prepare_analysis"
            )

    for key in ("evidence_store", "evidence_store_ids", "era_map", "quantitative_features"):
        value = prepare_result.get(key)
        if value is not None and not isinstance(value, dict):
            errors.append(f"prepare_result['{key}'] 必须是字典，实际为 {type(value).__name__}")
    if not isinstance(prepare_result.get("proper_noun_candidates", []), list):
        errors.append("prepare_result['proper_noun_candidates'] 必须是列表")

    return errors


def describe_prepare_contract() -> Dict[str, Any]:
    """Machine-readable contract description for diagnostics and docs."""
    return {
        "prepare_schema_version": PREPARE_SCHEMA_VERSION,
        "required_keys": list(REQUIRED_PREPARE_KEYS),
        "required_meta_keys": list(REQUIRED_META_KEYS),
        "optional_keys": list(OPTIONAL_PREPARE_KEYS),
    }
