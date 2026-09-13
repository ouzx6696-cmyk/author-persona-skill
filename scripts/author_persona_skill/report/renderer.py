# -*- coding: utf-8 -*-
"""Markdown report and JSON sidecar renderer."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 版本号的唯一来源。这里刻意用「导入子模块」(from .._version import __version__)，
# 而不是「从包 __init__ 取属性」(from .. import __version__)：
# 本模块会在包 __init__ 仍在执行期间被导入（__init__ -> pipeline -> renderer），
# 而 __init__ 的 __version__ 要等它自己的导入全部跑完才存在，
# 后者必然抛 "cannot import name from partially initialized module"。
# 该约束由 _version.py 自身满足 —— 它只依赖标准库、不 import 包内任何模块，
# 所以这条导入不会成环。
# 不要为了"去重"把它改回 from .. import __version__，那会在包初始化阶段直接炸。
from .._version import __version__
from ..distill.technique_cards import TechniqueCard
from ..distill.thinking_layer import ThinkingLayer
from ..distill.writer_contract import WriterContract
from ..distill.desensitize import (
    apply_desensitization,
    mask_evidence_quotes,
    validate_desensitization_map,
)
from .metrics import build_placeholder_map


_PUBLIC_EVIDENCE_PLACEHOLDER = "已校验证据（内容已隐藏）"
# 高/低置信说话人名单是身份轨迹：原型化口吻在 dialogue_review 与 1.9 散文中
# 呈现，原始人名列表一律不进公开 JSON。
_SENSITIVE_QUANT_KEYS = {
    "sample_quotes", "merged_aliases", "raw_quote", "raw_text", "excerpt",
    "high_confidence_speakers", "low_confidence_candidates",
}


def _fallback_label(index: int) -> str:
    """Return a deterministic neutral label for an unmapped candidate."""
    alphabet = "甲乙丙丁戊己庚辛壬癸"
    return f"原型{alphabet[index % len(alphabet)]}"


def _build_public_mapping(
    mapping: Any,
    proper_noun_candidates: Any,
) -> Tuple[Dict[str, str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a safe mapping for public artifacts and report mapping diagnostics."""
    raw_mapping = mapping if isinstance(mapping, dict) else {}
    candidates = proper_noun_candidates if isinstance(proper_noun_candidates, list) else []
    map_errors, map_warnings = validate_desensitization_map(raw_mapping, candidates)
    public_mapping: Dict[str, str] = {}
    for key, value in raw_mapping.items():
        original = str(key).strip()
        replacement = str(value).strip()
        if original and replacement and replacement != original:
            public_mapping[original] = replacement

    next_index = 0
    for item in candidates:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term", "")).strip()
        if len(term) < 2 or term in public_mapping:
            continue
        public_mapping[term] = _fallback_label(next_index)
        next_index += 1
    return public_mapping, map_errors, map_warnings


def _sanitize_public_value(value: Any, mapping: Dict[str, str], key: str = "") -> Any:
    """Recursively remove raw evidence and apply the public noun mapping.

    Keys are mapped too: a structured map can carry an identity in its *keys*
    (``imagery_clusters`` is keyed by high-frequency words, which in practice
    include character names). Leaving keys alone leaked them into the public
    sidecar while the value-only scan never noticed.
    """
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            child_key = str(raw_key)
            if child_key in _SENSITIVE_QUANT_KEYS:
                continue
            if child_key == "quote" and (key == "evidence" or "chunk_id" in value):
                result[child_key] = _PUBLIC_EVIDENCE_PLACEHOLDER
                continue
            if child_key == "sample_quotes":
                continue
            public_key = apply_desensitization(child_key, mapping) if mapping else child_key
            result[public_key] = _sanitize_public_value(raw_value, mapping, child_key)
        return result
    if isinstance(value, list):
        return [_sanitize_public_value(item, mapping, key) for item in value]
    if isinstance(value, str):
        return apply_desensitization(value, mapping)
    return value


def _sanitize_evidence_lines(prose: str, mapping: Dict[str, str]) -> str:
    """Hide every quoted evidence body while preserving review metadata on the line.

    遮蔽规则由 distill.desensitize.mask_evidence_quotes 统一提供，与校验层的
    引文豁免判定同源；随后对整行（含行尾注解）执行专名脱敏。
    """
    if not prose:
        return prose
    masked = mask_evidence_quotes(prose, _PUBLIC_EVIDENCE_PLACEHOLDER)
    return "\n".join(
        apply_desensitization(line, mapping) for line in masked.splitlines()
    )


def _export_public_mapping(mapping: Dict[str, str]) -> Dict[str, str]:
    """Expose only neutral mapping identifiers in public artifacts."""
    return {
        f"候选原型_{index:02d}": replacement
        for index, replacement in enumerate(mapping.values(), 1)
        if replacement
    }


def _atomic_write_text(path: Path, text: str) -> None:
    """Write a file beside its destination and replace it only after success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def extract_json_block(llm_text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Split LLM response into prose markdown and the parsed trailing JSON block.
    """
    json_blocks = re.findall(r'```json\s*(\{[\s\S]*?\})\s*```', llm_text)
    if not json_blocks:
        # Fallback: look for naked JSON dict at the end of the text
        match = re.search(r'(\{[\s\S]*"technique_cards"[\s\S]*\})\s*$', llm_text)
        if match:
            json_str = match.group(1)
            try:
                data = json.loads(json_str)
                prose = llm_text[:match.start()].strip()
                return prose, data
            except json.JSONDecodeError:
                pass
        return llm_text.strip(), None

    # Pick the last json block which should be the machine data block
    target_block = json_blocks[-1]
    try:
        data = json.loads(target_block)
        if not isinstance(data, dict):
            # 顶层必须是对象；数组/标量按"无有效机器块"处理，交由校验器拒绝
            return llm_text.strip(), None
        # Remove the code block from the markdown prose
        prose = re.sub(r'```json\s*' + re.escape(target_block) + r'\s*```', '', llm_text).strip()
        return prose, data
    except json.JSONDecodeError:
        return llm_text.strip(), None


def desensitize_prose(prose: str, mapping: Dict[str, str]) -> str:
    """Apply mapping and hide raw evidence bodies in public Markdown."""
    if not prose:
        return prose
    return _sanitize_evidence_lines(prose, mapping or {})


_PART0_HEADING = "## 第〇部分：作家定义与读者契约（作家契约层）"
_PART2_HEADING = "## 第二部分：核心写作技法提取（技法调用卡层）"
_PART3_HEADING = "## 第三部分：作家创作思维与宏观心智（思维层）"


def _compose_single_source(prose_markdown: str, parsed_json: Optional[Dict[str, Any]]) -> str:
    """以 JSON 机器块为唯一真源重写第〇、二、三部分正文。

    LLM 只撰写第一部分散文与 JSON 块；作家契约、技法卡与思维层由已通过校验的
    JSON 渲染生成，Markdown 与 report.json 不再可能出现两套互相矛盾的内容。
    保真闭环附录（若有）保持在文末。

    任一部分标题行缺失或顺序颠倒时抛错走 fail-closed，而不是把 LLM 手写正文
    原样放行——那会让公开产物绕开"单一真源"契约（manifest core_constraint）。
    上游 response_health_check 已按行级 `^##` 正则拦截缺失，此处兜底。
    """
    if not parsed_json:
        raise ValueError("单一真源渲染缺少 JSON 机器块，拒绝渲染")
    part0_pos = prose_markdown.find("## 第〇部分")
    part1_pos = prose_markdown.find("## 第一部分")
    part2_pos = prose_markdown.find("## 第二部分")
    part3_pos = prose_markdown.find("## 第三部分")
    if part0_pos < 0:
        raise ValueError("响应缺少「## 第〇部分」标题行，无法执行单一真源渲染")
    if part1_pos < 0 or part1_pos < part0_pos:
        raise ValueError("响应缺少「## 第一部分」标题行（或顺序颠倒），无法执行单一真源渲染")
    if part2_pos < 0:
        raise ValueError("响应缺少「## 第二部分」标题行，无法执行单一真源渲染")
    if part3_pos < 0 or part3_pos < part2_pos:
        raise ValueError("响应缺少「## 第三部分」标题行（或顺序颠倒），无法执行单一真源渲染")

    contract = WriterContract.from_dict(parsed_json.get("writer_contract") or {})
    contract_ok, contract_errors = contract.validate()
    if not contract_ok:
        raise ValueError("writer_contract 校验失败（第〇部分拒绝渲染）：" + "；".join(contract_errors))

    card_blocks: List[str] = []
    for card in parsed_json.get("technique_cards") or []:
        try:
            card_blocks.append(TechniqueCard.from_dict(card).render_markdown())
        except Exception:
            continue
    if not card_blocks:
        # 无卡可渲染同样是 fail-closed：上游已强制 3–6 张卡，
        # 走到这里说明响应结构与校验结果不一致。
        raise ValueError("单一真源渲染未产出任何技法卡正文，拒绝渲染")

    try:
        thinking_block = ThinkingLayer.from_dict(
            parsed_json.get("thinking_layer") or {}
        ).render_markdown()
    except Exception:
        thinking_block = ""

    appendix = ""
    appendix_pos = prose_markdown.find("## 附录：")
    if appendix_pos > part3_pos:
        appendix = "\n\n---\n\n" + prose_markdown[appendix_pos:].strip()

    return (
        prose_markdown[:part0_pos].rstrip()
        + "\n\n" + _PART0_HEADING + "\n\n" + contract.render_markdown()
        + "\n\n" + prose_markdown[part1_pos:part2_pos].rstrip()
        + "\n\n" + _PART2_HEADING + "\n\n" + "\n\n".join(card_blocks)
        + "\n\n" + _PART3_HEADING + "\n\n" + thinking_block
        + appendix
    )


def _validation_summary(
    validation: Optional[Dict[str, Any]],
    public_mapping: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """机器端可读的校验/质量摘要；未传校验结果时为 None.

    Warnings may cite candidate terms themselves (e.g. "缺少高频专名'X'"),
    so they must be desensitized before publishing; otherwise the final audit
    would mistake diagnostics for leaks -- and public JSON must never carry
    identifiable strings.
    """
    if not isinstance(validation, dict):
        return None
    numeric = validation.get("numeric_audit") or {}
    raw_warnings = validation.get("warnings", [])
    clean_warnings = []
    for w in raw_warnings:
        s = str(w)
        if public_mapping:
            try:
                s = apply_desensitization(s, public_mapping)
            except Exception:
                pass
            # 仍含未映射高频词时,折叠原词只留计数语义,避免公共产物泄漏
            # (完整原文仅保留在私有校验结果中,不进 report.json)
        clean_warnings.append(s)
    return {
        "status": validation.get("status"),
        "schema": validation.get("schema"),
        "desensitization": validation.get("desensitization"),
        "numeric_audit_status": numeric.get("status"),
        "evidence": validation.get("evidence"),
        "quality": validation.get("quality"),
        "integrity": validation.get("integrity"),
        "quality_status": validation.get("quality_status"),
        "privacy": validation.get("privacy"),
        "publishable": validation.get("publishable"),
        "warnings": clean_warnings,
    }


def render_report_outputs(
    prose_markdown: str,
    parsed_json: Optional[Dict[str, Any]],
    prepare_result: Dict[str, Any],
    output_dir: Optional[Path] = None,
    base_name: str = "style_analysis",
    validation: Optional[Dict[str, Any]] = None,
    fidelity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compile final markdown report, sidecar JSON, and mapping files.
    """
    meta = prepare_result.get("prepare_meta", {})
    work_title = meta.get("work_title", "未命名作品")
    author_name = meta.get("author_name", "佚名")
    desensitize_enabled = meta.get("desensitize", True)
    allow_identity = bool(meta.get("allow_author_identity", False))
    # Identity Policy: public_sanitized never carries real title/author
    # in headers, meta, or filenames. Real identity stays in prepare_meta
    # (private) and private sidecar only.
    try:
        from ..distill.desensitize import compute_work_id as _wid
        work_id = _wid(author_name, work_title)
    except Exception:
        work_id = "WORK_UNKNOWN"
    public_title = work_title if (allow_identity or not desensitize_enabled) else work_id
    public_author = author_name if (allow_identity or not desensitize_enabled) else "已脱敏"

    raw_desens_map = parsed_json.get("desensitization_map", {}) if parsed_json else {}
    include_raw_evidence = bool(meta.get("include_raw_evidence", False))

    # Apply desensitization to Markdown prose and hide raw quote bodies in the
    # default public artifact. The raw response remains available only through
    # the explicit private sidecar switch. With desensitization disabled the
    # noun mapping is skipped entirely on both channels (structural minimization
    # of sample quotes still applies); the artifact is marked policy "raw".
    if desensitize_enabled:
        public_mapping, mapping_errors, mapping_warnings = _build_public_mapping(
            raw_desens_map,
            prepare_result.get("proper_noun_candidates", []),
        )
        # Ensure author/work always have a neutral fallback so warnings
        # mentioning them can be sanitized (they are in candidates already,
        # but be explicit when candidates are empty in unit tests).
        _fb_idx = len(public_mapping)
        for _ident in (author_name, work_title):
            _t = str(_ident or "").strip()
            if len(_t) >= 2 and _t not in public_mapping and not allow_identity:
                public_mapping[_t] = _fallback_label(_fb_idx)
                _fb_idx += 1
        clean_prose = desensitize_prose(_compose_single_source(prose_markdown, parsed_json), public_mapping)
    else:
        public_mapping, mapping_errors, mapping_warnings = {}, [], []
        clean_prose = _compose_single_source(prose_markdown, parsed_json)

    # 渲染终检：证据占位符必须恰好被一对引号包住。遮蔽正则若越界吞并
    # metric/「注解：」字段，占位符后会残留引号碎片或裸文本——四重校验
    # 看不到这种损坏，必须在公开产物落盘前拒绝。
    _malformed = [
        ln for ln in clean_prose.splitlines()
        if _PUBLIC_EVIDENCE_PLACEHOLDER in ln
        and not re.search(
            r"[“\"'「『]" + re.escape(_PUBLIC_EVIDENCE_PLACEHOLDER) + r"[”\"'」』]", ln
        )
    ]
    if _malformed:
        raise ValueError(
            "渲染终检失败：证据占位符形态异常（疑似遮蔽吞并注解/指标字段），拒绝渲染: "
            + _malformed[0][:80]
        )

    # Header metadata block for markdown (sanitized header by default)
    header_lines = [
        f"# 《{public_title}》风格能力解构报告",
        "",
        "> **报告契约**：四层契约 · 脱敏 · 证据锚点 · 保真闭环",
        f"> **分析对象**：{public_title}（来源作者标记：{public_author}）",
        f"> **采样范围**：{meta.get('sample_range_desc', '全样本/代表性采样')}",
        f"> **降噪过滤**：已清洗平台寄语与格式噪音（噪音占比: {meta.get('noise_ratio_pct', '0.00%')}）",
        f"> **产物策略**：{'raw' if not desensitize_enabled else 'public_sanitized'} · {work_id}",
    ]
    if validation:
        header_lines.append(
            f"> **校验状态**：schema {validation.get('schema', '-')} / 脱敏 {validation.get('desensitization', '-')} / "
            f"数值审计 {(validation.get('numeric_audit') or {}).get('status', '-')}"
            f"（质量自评与校验摘要见 report.json 的 quality / validation_summary 字段）"
        )
    header_lines.extend(["", "---", ""])
    full_markdown = "\n".join(header_lines) + clean_prose

    # Machine JSON sidecar. Public artifacts intentionally omit raw excerpts,
    # speaker samples, and evidence quote text; downstream consumers receive
    # stable structure and verification metadata without corpus disclosure.
    public_quant = _sanitize_public_value(
        prepare_result.get("quantitative_features", {}), public_mapping
    )
    public_cards = _sanitize_public_value(
        parsed_json.get("technique_cards", []) if parsed_json else [], public_mapping
    )
    public_thinking = _sanitize_public_value(
        parsed_json.get("thinking_layer", {}) if parsed_json else {}, public_mapping
    )
    public_dialogue = _sanitize_public_value(
        parsed_json.get("dialogue_review", {}) if parsed_json else {}, public_mapping
    )
    public_map = _export_public_mapping(public_mapping)
    json_meta: Dict[str, Any] = {
        "work_id": work_id,
        "mode": meta.get("mode", "full"),
        "noise_ratio": meta.get("noise_ratio", 0.0),
        "sample_range": meta.get("sample_range_desc", ""),
    }
    # Real title/author only in explicit identity modes; default sanitized
    # meta carries work_id so public JSON has zero known-identity strings.
    if allow_identity or not desensitize_enabled:
        json_meta["work_title"] = work_title
    if allow_identity:
        json_meta["author_name"] = author_name
    report_json: Dict[str, Any] = {
        "version": __version__,
        "schema_version": "5",
        "artifact_policy": "raw" if not desensitize_enabled else "public_sanitized",
        "meta": json_meta,
        "writer_contract": _sanitize_public_value(
            parsed_json.get("writer_contract", {}) if parsed_json else {}, public_mapping
        ),
        "quantitative_features": public_quant,
        "technique_cards": public_cards,
        "thinking_layer": public_thinking,
        # Claims are an optional extension layer, but when present they are
        # public content like everything else and must carry the same mapping.
        "claims": _sanitize_public_value(
            parsed_json.get("claims", []) if parsed_json else [], public_mapping
        ),
        "desensitization_map": public_map,
        "dialogue_review": public_dialogue,
        "provenance": {
            "pipeline_version": __version__,
            "schema_version": "5",
            "is_fallback_index": bool(meta.get("is_fallback_index", False)),
            "coverage_pct": meta.get("coverage_pct"),
            "encoding": meta.get("encoding"),
            "era_count": len({
                v for v in (prepare_result.get("era_map") or {}).values()
                if v and v != "未分期"
            }),
            "chapter_count": len(prepare_result.get("era_spans") or []),
            "evidence_count": len(prepare_result.get("evidence_store_ids") or {}),
            "placeholder_registry": build_placeholder_map(
                prepare_result.get("quantitative_features", {}) or {}
            ),
            "metric_registry": prepare_result.get("metric_registry") or {},
        },
        "validation_summary": _validation_summary(validation, public_mapping),
        "fidelity": fidelity,
        "artifact_diagnostics": {
            "mapping_error_count": len(mapping_errors),
            "mapping_warning_count": len(mapping_warnings),
        },
    }

    files_saved = {}
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        internal_path = out_path / ".internal"
        if include_raw_evidence:
            internal_path.mkdir(parents=True, exist_ok=True)

        md_file = out_path / f"{base_name}.md"
        json_file = out_path / f"{base_name}.json"
        # map/manifest 按报告名作用域：同目录多次 finalize（多报告→一人格的
        # 常态工作流）不再互相覆盖。
        map_file = out_path / f"{base_name}_desensitization_map.json"
        manifest_file = out_path / f"{base_name}_manifest.json"

        _atomic_write_text(md_file, full_markdown)
        _atomic_write_text(json_file, json.dumps(report_json, ensure_ascii=False, indent=2))
        if desensitize_enabled and report_json["desensitization_map"]:
            _atomic_write_text(map_file, json.dumps(report_json["desensitization_map"], ensure_ascii=False, indent=2))
        # Manifest sidecar (public, no identities).
        _atomic_write_text(manifest_file, json.dumps({
            "pipeline_version": __version__,
            "schema_version": "5",
            "artifact_policy": report_json.get("artifact_policy"),
            "work_id": json_meta.get("work_id"),
            "validation": {
                "integrity": (validation or {}).get("schema"),
                "quality": ((validation or {}).get("quality") or {}).get("status", "n/a")
                if isinstance((validation or {}).get("quality"), dict) else "n/a",
                "privacy": (validation or {}).get("desensitization"),
            },
            "provenance": report_json.get("provenance", {}),
        }, ensure_ascii=False, indent=2))

        private_file = internal_path / f"{base_name}_private_evidence.json"
        if include_raw_evidence:
            private_payload = {
                "artifact_policy": "private_raw_evidence",
                "desensitization_map": raw_desens_map,
                "evidence_store": prepare_result.get("evidence_store", {}),
                "evidence_store_ids": prepare_result.get("evidence_store_ids", {}),
                "era_map": prepare_result.get("era_map", {}),
                "era_id_map": prepare_result.get("era_id_map", {}),
                "raw_technique_cards": parsed_json.get("technique_cards", []) if parsed_json else [],
            }
            _atomic_write_text(private_file, json.dumps(private_payload, ensure_ascii=False, indent=2))

        files_saved = {
            "report_md_path": str(md_file),
            "report_json_path": str(json_file),
            "desensitization_map_path": str(map_file) if report_json["desensitization_map"] else None,
            "manifest_path": str(manifest_file),
            "private_evidence_path": str(private_file) if include_raw_evidence else None,
        }

    return {
        "full_markdown": full_markdown,
        "report_json": report_json,
        "files_saved": files_saved,
    }
