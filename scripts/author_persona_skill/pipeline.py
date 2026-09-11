# -*- coding: utf-8 -*-
"""The three-stage pipeline.

    prepare_analysis   local measurement -> prompt + evidence store (no LLM)
    (the agent calls the LLM)
    finalize_analysis  response -> validation -> rendered artifacts

Everything in this module is pure standard library and deterministic. The
hand-off between stage 1 and stage 3 is declared in ``contracts.py`` and
checked at the top of ``finalize_analysis``, so a stale or truncated
``prepare_result`` fails with an actionable message instead of a KeyError deep
inside the renderer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .analyzers.noise import filter_noise
from ._version import __version__
from .analyzers.style_analyzer import StyleAnalyzer
from .contracts import PREPARE_SCHEMA_VERSION, validate_prepare_result
from .corpus.file_processor import read_text_file
from .corpus.chapter_index import build_chapter_index
from .corpus.reading_plan import create_reading_plan
from .distill.evidence import (
    build_chunk_offsets,
    build_evidence_store,
    create_chunks,
    extract_candidate_evidence_pool,
)
from .distill.desensitize import (
    compute_work_id,
    extract_proper_noun_candidates,
    scan_artifact,
    validate_desensitization,
)
from .report.health import check_response_health
from .report.metrics import (
    build_metric_registry,
    build_placeholder_map,
    find_unresolved_metric_refs,
    find_unresolved_tokens,
    render_placeholder_table,
    substitute_metric_refs,
    substitute_placeholders,
)
from .report.repair import attach_repair
from .report.templates import MASTER_SYSTEM_PROMPT, build_analysis_prompt
from .report.renderer import (
    _atomic_write_text,
    extract_json_block,
    render_report_outputs,
)
from .report.validator import validate_report
from .fidelity.fidelity_check import run_fidelity_check
from .persona.system_prompt import build_system_prompt

ERA_ORDER = (
    "开头 (Begin)", "发展 (Develop)", "成熟 (Mature)", "演变 (Evolve)", "结尾 (Ending)",
)


# ---------------------------------------------------------------------------
# prepare-stage helpers
# ---------------------------------------------------------------------------

def _chunk_era_maps(
    chunks: Dict[str, str],
    sampled_chapters: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Map every chunk id to (era label, era_id) of the chapter its start falls in.

    ``create_chunks()`` concatenates source lines verbatim, so the sum of all
    chunk lengths equals ``len(sampled_text)`` and no separator is inserted
    between chunks. An earlier version added a chapter-level "\\n\\n" separator
    to the cursor, which made the cursor drift further off with every chunk and
    mislabelled chunks near chapter boundaries.
    """
    chapters = sorted(sampled_chapters, key=lambda c: c.get("start", 0))

    def locate(position: int) -> Tuple[str, str]:
        for chapter in chapters:
            if chapter.get("start", 0) <= position < chapter.get("end", 0):
                return str(chapter.get("era", "未分期")), str(chapter.get("era_id", ""))
        return "未分期", ""

    era_map: Dict[str, str] = {}
    era_id_map: Dict[str, str] = {}
    cursor = 0
    for chunk_id, chunk_text in chunks.items():
        era_map[chunk_id], era_id_map[chunk_id] = locate(cursor)
        cursor += len(chunk_text)
    return era_map, era_id_map


def _build_era_excerpts(
    chunks: Dict[str, str],
    era_map: Dict[str, str],
    chars_per_era: int = 900,
) -> List[Dict[str, Any]]:
    """Pick one representative mid-position chunk per era as grounding excerpt."""
    groups: Dict[str, List[str]] = {}
    for chunk_id in sorted(chunks.keys()):
        groups.setdefault(era_map.get(chunk_id, "未分期"), []).append(chunk_id)

    ordered_eras = [era for era in ERA_ORDER if era in groups]
    ordered_eras += [era for era in groups if era not in ordered_eras]

    excerpts: List[Dict[str, Any]] = []
    for era in ordered_eras:
        chunk_ids = groups[era]
        middle = chunk_ids[len(chunk_ids) // 2]
        excerpts.append({
            "chunk_id": middle,
            "era": era,
            "excerpt": chunks[middle].strip()[:chars_per_era],
        })
    return excerpts


def _build_era_window_metrics(
    chunks: Dict[str, str],
    era_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Per-era style metrics, used as the author's own natural variation band.

    The fidelity loop compares a trial text against the whole-book baseline; the
    per-era windows tell it how much the author themselves varies, so a metric
    that moves within the author's natural range is not reported as a drift.
    """
    groups: Dict[str, List[str]] = {}
    for chunk_id in sorted(chunks.keys()):
        groups.setdefault(era_map.get(chunk_id, "未分期"), []).append(chunk_id)

    analyzer = StyleAnalyzer()
    windows: List[Dict[str, Any]] = []
    for era in [e for e in ERA_ORDER if e in groups] + [e for e in groups if e not in ERA_ORDER]:
        text = "\n".join(chunks[cid] for cid in groups[era])
        if len(text.strip()) < 200:
            continue
        metrics = analyzer.analyze(text, pre_cleaned=True)
        metrics["era"] = era
        windows.append(metrics)
    return windows


def _build_placeholder_table(quant_features: Dict[str, Any]) -> str:
    placeholder_map = build_placeholder_map(quant_features)
    metric_registry = build_metric_registry(quant_features)
    lines = ["| MID | 占位符别名 | 实测值 | scope |", "|---|---|---|---|"]
    for mid in sorted(metric_registry):
        entry = metric_registry[mid]
        lines.append(
            f"| {mid} | {{{{{entry['token']}}}}} / {{{{metric:{mid}}}}} | {entry['value']} | {entry['scope']} |")
    return render_placeholder_table(placeholder_map) + "\n\n" + "\n".join(lines)


def prepare_analysis(
    corpus_path: Optional[str | Path] = None,
    corpus_text: Optional[str] = None,
    author_name: str = "",
    work_title: str = "",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Stage 1: measure the corpus locally and build the LLM prompt.

    Returns the hand-off dict declared in ``contracts.py``. The two fields the
    agent needs to call the LLM are ``llm_system_msg`` and ``llm_prompt``; every
    other key is provenance for ``finalize_analysis``.
    """
    opts = options or {}
    desensitize = opts.get("desensitize", True)
    generate_system_prompt = opts.get("generate_system_prompt", False)
    allow_author_identity = opts.get("allow_author_identity", False)
    include_raw_evidence = opts.get("include_raw_evidence", False)
    sample_budget_chars = opts.get("sample_budget_chars", 150000)
    if not isinstance(sample_budget_chars, int) or sample_budget_chars <= 0:
        raise ValueError("sample_budget_chars 必须为正整数。")

    # 1. Load raw text.
    if corpus_path:
        raw_text, detected_enc = read_text_file(corpus_path)
    elif corpus_text is not None:
        raw_text = str(corpus_text)
        detected_enc = "in-memory"
    else:
        raise ValueError("Either corpus_path or corpus_text must be provided.")
    if not work_title and corpus_path:
        work_title = Path(corpus_path).stem.replace(".txt", "")

    # 2. Whole-book noise filtering. Every later statistic either uses the clean
    #    full text (noise ratio) or the sampled subset; both bases stay explicit.
    clean_full_text, noise_ratio, noise_stats = filter_noise(raw_text)
    if len(clean_full_text.strip()) < 50:
        raise ValueError("语料为空或降噪后无有效正文，无法进行风格分析。")

    # 3. Chapter index and five-era stratified reading plan.
    chapters, is_fallback = build_chapter_index(clean_full_text)
    plan = create_reading_plan(
        text=clean_full_text,
        chapters=chapters,
        budget_chars=sample_budget_chars,
        is_fallback=is_fallback,
    )
    working_text = plan["sampled_text"]

    # 4. Quantitative style analysis (text already noise-filtered in step 2).
    analyzer = StyleAnalyzer()
    quant_features = analyzer.analyze(
        working_text, chapters_meta=plan["sampled_chapters"], pre_cleaned=True)
    quant_features["text_summary"]["noise_ratio"] = noise_ratio
    quant_features["text_summary"]["noise_ratio_pct"] = noise_stats["noise_ratio_pct"]
    quant_features["text_summary"]["noise_stats"] = noise_stats
    quant_features["text_summary"]["full_clean_chars"] = len(clean_full_text)
    quant_features["text_summary"]["sample_note"] = (
        f"全书清洗后 {len(clean_full_text):,} 字符，样本为其中采样子集 "
        f"({plan['coverage_pct']}%)；字符统计以样本为准，噪音占比为全书口径"
    )

    # 5. Chunked trusted evidence store. Anchors are era-balanced so the pool
    #    spans the whole sampling range instead of clustering at the opening.
    chunks = create_chunks(working_text, chunk_size=2000, chunk_prefix="c")
    era_map, era_id_map = _chunk_era_maps(chunks, plan["sampled_chapters"])
    era_spans = [
        {
            "start": chapter.get("start", 0),
            "end": chapter.get("end", 0),
            "era": chapter.get("era", "未分期"),
            "era_id": chapter.get("era_id", ""),
            "chapter_id": chapter.get("chapter_id", ""),
            "chapter_idx": chapter.get("chapter_idx", 0),
        }
        for chapter in sorted(plan["sampled_chapters"], key=lambda c: c.get("start", 0))
    ]
    evidence_pool = extract_candidate_evidence_pool(
        chunks, max_items=28, era_map=era_map, era_id_map=era_id_map)
    chunk_offsets = build_chunk_offsets(chunks)
    evidence_store_ids = build_evidence_store(evidence_pool, chunks, chunk_offsets, era_spans)
    era_excerpts = _build_era_excerpts(chunks, era_map)
    era_window_metrics = _build_era_window_metrics(chunks, era_map)

    # 6. Proper-noun watch list. Speakers come from the dialogue analyzer -- the
    #    single authority on who speaks in this corpus.
    dialogue_info = quant_features.get("dialogue_features", {})
    proper_nouns = extract_proper_noun_candidates(
        working_text,
        top_n=50,
        author_name=author_name,
        work_title=work_title,
        speakers=dialogue_info.get("high_confidence_speakers", []),
    )
    dialogue_candidates = {
        "high_confidence_speakers": dialogue_info.get("high_confidence_speakers", []),
        "low_confidence_candidates": dialogue_info.get("low_confidence_candidates", []),
    }

    # 7. Prompt assembly.
    prompt = build_analysis_prompt(
        quantitative_data=quant_features,
        evidence_pool=evidence_pool,
        proper_noun_candidates=proper_nouns,
        dialogue_candidates=dialogue_candidates,
        author_name=author_name,
        work_title=work_title,
        generate_system_prompt=generate_system_prompt,
        allow_author_identity=allow_author_identity,
        era_excerpts=era_excerpts,
        placeholder_table=_build_placeholder_table(quant_features),
    )

    prepare_meta = {
        "prepare_schema_version": PREPARE_SCHEMA_VERSION,
        "author_name": author_name,
        "work_title": work_title,
        # light 模式已移除；字段保留常量以稳定 report.json 的 meta 结构
        "mode": "full",
        "desensitize": desensitize,
        "generate_system_prompt": generate_system_prompt,
        "allow_author_identity": allow_author_identity,
        "include_raw_evidence": include_raw_evidence,
        "noise_ratio": noise_ratio,
        "noise_ratio_pct": noise_stats["noise_ratio_pct"],
        "sample_range_desc": plan["sample_range_desc"],
        "coverage_pct": plan["coverage_pct"],
        "is_fallback_index": is_fallback,
        "encoding": detected_enc,
        "pipeline_version": __version__,
        "artifact_policy": "raw" if not desensitize else "public_sanitized",
    }

    return {
        "llm_prompt": prompt,
        "llm_system_msg": MASTER_SYSTEM_PROMPT,
        "evidence_store": chunks,
        "evidence_pool": evidence_pool,
        "evidence_store_ids": evidence_store_ids,
        "chunk_offsets": chunk_offsets,
        "era_map": era_map,
        "era_id_map": era_id_map,
        "era_spans": era_spans,
        "era_excerpts": era_excerpts,
        "era_ranges": plan.get("era_ranges", []),
        "era_window_metrics": era_window_metrics,
        "quantitative_features": quant_features,
        "metric_registry": build_metric_registry(quant_features),
        "placeholder_map": build_placeholder_map(quant_features),
        "proper_noun_candidates": proper_nouns,
        "prepare_meta": prepare_meta,
    }


# ---------------------------------------------------------------------------
# finalize-stage helpers
# ---------------------------------------------------------------------------

def _resolve_base_name(meta: Dict[str, Any], base_name: Optional[str]) -> str:
    """Filename stem. The sanitized default never carries the real title."""
    if base_name:
        return base_name
    work_title = meta.get("work_title", "style_analysis")
    if meta.get("desensitize", True) and not meta.get("allow_author_identity", False):
        return f"{compute_work_id(meta.get('author_name', ''), work_title)}_风格解构报告"
    return f"{work_title}_风格解构报告"


def _failed_result(
    validation: Dict[str, Any],
    rejected_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Uniform return shape for every rejection path."""
    return {
        "report_content": None,
        "report_json": None,
        "report_path": None,
        "report_json_path": None,
        "desensitization_map_path": None,
        "rejected_path": rejected_path,
        "validation": validation,
        "fidelity": None,
        "system_prompt": None,
        "repair_prompt": validation.get("repair_prompt"),
        "files_saved": {"rejected_path": rejected_path},
        "status": "failed",
    }


def _write_rejected(
    out_dir: Optional[Path],
    file_base_name: str,
    work_title: str,
    validation: Dict[str, Any],
    prose_markdown: str,
) -> Optional[str]:
    """Persist the raw response for private diagnosis; never a public artifact."""
    if not out_dir:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    rejected_path = out_dir / f"{file_base_name}_rejected.md"
    failure_note = "\n".join(f"> - {error}" for error in validation["errors"]) or "> - 未知原因"
    _atomic_write_text(rejected_path, (
        f"# 【已拒绝】{work_title} 风格能力报告\n\n"
        f"> 本响应未通过技能校验，禁止作为正式产物使用。失败原因：\n"
        f"{failure_note}\n\n"
        f"> 修复提示词见 validation.repair_prompt（同一会话内追加即可重试）。\n"
        f"> 隐私警告：本文件包含未脱敏的原始响应内容，仅限私有保存与排查，禁止公开分发。\n"
        f"\n---\n\n{prose_markdown}"
    ))
    return str(rejected_path)


def _render_fidelity_appendix(fidelity_result: Dict[str, Any]) -> str:
    """Markdown appendix for the trial-writing closed loop."""
    deviation_rows = "\n".join(
        f"| {row.get('metric', '?')} | {row.get('reference', '?')} | "
        f"{row.get('trial', '?')} | {row.get('status', '?')} |"
        for row in fidelity_result.get("deviations_table", [])
    ) or "| - | - | - | - |"
    card_rows = "\n".join(
        f"| {item.get('id', '?')} | {item.get('name', '?')} | "
        f"{item.get('status', '?')} | {item.get('notes', '')} |"
        for item in fidelity_result.get("technique_card_evaluations", [])
    ) or "| - | - | - | - |"
    scene_rows = "\n".join(
        f"| {row['scene']} | {row['chars']} | {row['avg_sent_len']} | {row['dialogue_ratio_pct']} |"
        for row in ((fidelity_result.get("probe_summary") or {}).get("detail") or [])
    ) or "| - | - | - | - |"

    copy_check = fidelity_result.get("copy_check") or {}
    copy_line = (
        f"\n**复制检测**：{'通过' if fidelity_result.get('copy_passed', True) else '未通过'}"
        f"（最长连续一致{copy_check.get('longest_match', 0)}字，"
        f"5-gram重叠{copy_check.get('five_gram_overlap', 0)}）\n"
        if copy_check else "")
    probe = fidelity_result.get("probe_summary") or {}
    probe_line = (
        f"\n**多探针**：{probe.get('adequate', 0)}/{probe.get('total', 0)}场景达标（≥800字）。\n"
        if probe.get("total") else "")
    return (
        "\n\n---\n\n## 附录：保真闭环校验（试写文本 vs 基线指标）\n\n"
        f"**结论**：{'通过' if fidelity_result.get('status') == 'passed' else '未通过'}\n"
        f"{copy_line}{probe_line}\n"
        f"| 指标 | 基线 | 试写 | 判定 |\n|---|---|---|---|\n{deviation_rows}\n\n"
        "### 技法卡逐项判定\n\n| ID | 技法 | 状态 | 说明 |\n|---|---|---|---|\n"
        f"{card_rows}\n\n"
        "### 分场景指标\n\n| 场景 | 字符数 | 平均句长 | 对话占比 |\n|---|---|---|---|\n"
        f"{scene_rows}\n"
    )


def _copy_reference_texts(prepare_result: Dict[str, Any], limit: int = 10) -> List[str]:
    """Era-balanced chunks for copy detection.

    Taking the first N chunks would compare the trial against the opening only
    and could miss plagiarism from the middle of the book.
    """
    chunks = prepare_result.get("evidence_store") or {}
    era_map = prepare_result.get("era_map") or {}
    groups: Dict[str, List[str]] = {}
    for chunk_id in sorted(chunks):
        groups.setdefault(era_map.get(chunk_id, "未分期"), []).append(chunk_id)
    texts: List[str] = []
    while len(texts) < limit:
        progressed = False
        for era in list(groups):
            if len(texts) >= limit:
                break
            ids = groups[era]
            if not ids:
                continue
            texts.append(chunks[ids.pop(len(ids) // 2)])
            progressed = True
        if not progressed:
            break
    return texts


def _final_artifact_audit(
    rendered: Dict[str, Any],
    prepare_result: Dict[str, Any],
    meta: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Recursive identity scan over the rendered JSON *and* Markdown.

    This is the last gate before files are published: the renderer already
    applied the public mapping, so any hit here is a real leak. Markdown is
    audited separately because evidence quote lines are exempt in the body
    scanner but headers never are.
    """
    candidates = prepare_result.get("proper_noun_candidates", [])
    author = "" if meta.get("allow_author_identity", False) else meta.get("author_name", "")
    # In sanitized mode the real title must not appear anywhere public; the
    # renderer already replaced it with WORK_xxxx, so any occurrence is a leak.
    title = "" if meta.get("allow_author_identity", False) else meta.get("work_title", "")

    leaks = list(scan_artifact(dict(rendered["report_json"]), candidates, author, title))
    if leaks:
        return leaks
    _passed, markdown_leaks = validate_desensitization(
        rendered["full_markdown"], candidates, author, title)
    return [
        {
            "term": leak.get("term", ""),
            "type": leak.get("type", ""),
            "count": leak.get("count", 0),
            "path": "report.md",
            "reason": f"Identity term '{leak.get('term','')}' found in public Markdown",
        }
        for leak in markdown_leaks
    ]


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------

def finalize_analysis(
    prepare_result: Dict[str, Any],
    llm_response: str,
    output_dir: Optional[str | Path] = None,
    base_name: Optional[str] = None,
    trial_text: Optional[str | List[str]] = None,
) -> Dict[str, Any]:
    """Stage 3: parse the response, validate it, and render the artifacts.

    A response that fails validation never becomes an official report: only
    ``{base}_rejected.md`` is written (plus a ``repair_prompt`` for the retry).
    ``trial_text`` additionally runs the fidelity closed loop, whose result is
    appended to the report and returned. The two are independent: a fidelity
    miss keeps the report but sets ``status`` to ``failed``.
    """
    # 0. Stage contract: fail fast and actionably on a stale/incomplete hand-off.
    contract_errors = validate_prepare_result(prepare_result)
    if contract_errors:
        return _failed_result({
            "status": "failed",
            "schema": "failed",
            "desensitization": "failed",
            "numeric_audit": {"status": "failed", "conflicts": []},
            "evidence": {},
            "quality": {},
            "errors": [f"prepare_result 不满足阶段契约：{error}" for error in contract_errors],
            "warnings": [],
            "unresolved_placeholders": [],
        })

    meta = prepare_result.get("prepare_meta", {})
    work_title = meta.get("work_title", "style_analysis")
    file_base_name = _resolve_base_name(meta, base_name)
    out_dir_path = Path(output_dir) if output_dir else None

    # 1. Placeholder substitution -> prose/JSON split -> structural health check
    #    -> four-gate validation. Fail-closed: any unexpected exception becomes
    #    a rejection, never a crash.
    quant_features = prepare_result.get("quantitative_features", {}) or {}
    prose_markdown = ""
    parsed_json: Optional[Dict[str, Any]] = None
    unresolved: List[str] = []
    health_errors: List[str] = []
    validation: Dict[str, Any] = {}
    try:
        placeholder_map = prepare_result.get("placeholder_map") or build_placeholder_map(quant_features)
        registry = prepare_result.get("metric_registry") or build_metric_registry(quant_features)
        substituted = substitute_placeholders(llm_response, placeholder_map)
        substituted = substitute_metric_refs(substituted, registry)
        prose_markdown, parsed_json = extract_json_block(substituted)
        unresolved = find_unresolved_tokens(substituted)
        unresolved_mids = find_unresolved_metric_refs(substituted, registry)
        health_errors = check_response_health(prose_markdown)
        if unresolved:
            health_errors.append(f"存在无法解析的数值占位符（未在注册表中定义）：{', '.join(unresolved)}")
        if unresolved_mids:
            health_errors.append(f"存在无法解析的指标引用（未在MID注册表中定义）：{', '.join(unresolved_mids)}")
        validation = validate_report(
            prose_markdown=prose_markdown,
            parsed_json=parsed_json,
            prepare_result=prepare_result,
        )
    except Exception as exc:  # noqa: BLE001 - fail-closed: reject instead of crash
        validation = {
            "status": "failed",
            "schema": "failed",
            "desensitization": "failed",
            "numeric_audit": {"status": "failed", "conflicts": []},
            "evidence": {},
            "quality": {},
            "errors": [f"校验链异常（fail-closed 拒绝）：{type(exc).__name__}: {exc}"],
            "warnings": [],
        }
    validation["errors"] = list(validation.get("errors", [])) + health_errors
    validation["unresolved_placeholders"] = unresolved
    validation["status"] = (
        "passed" if (validation.get("schema") == "passed"
                     and validation.get("desensitization") == "passed"
                     and not validation["errors"]) else "failed"
    )

    # 2. Rejection path: never render official artifacts from a failing response.
    if validation["status"] != "passed":
        attach_repair(validation, prepare_result, parsed_json)
        rejected_path = _write_rejected(
            out_dir_path, file_base_name, work_title, validation, prose_markdown)
        return _failed_result(validation, rejected_path)

    # 3. Optional fidelity closed loop. run_fidelity_check is the single
    #    enforcement point for the scene contract (2-3 scenes, >=800 chars each,
    #    type coverage when labelled), shared with the standalone CLI path.
    fidelity_result = None
    fidelity_appendix = ""
    if trial_text:
        try:
            fidelity_result = run_fidelity_check(
                trial_text=trial_text,
                reference_metrics=quant_features,
                technique_cards=(parsed_json or {}).get("technique_cards") or None,
                reference_texts=_copy_reference_texts(prepare_result),
                window_metrics=prepare_result.get("era_window_metrics") or None,
            )
            fidelity_appendix = _render_fidelity_appendix(fidelity_result)
        except Exception as exc:  # noqa: BLE001 - expose the failure, keep diagnostics
            fidelity_result = {"status": "failed", "error": str(exc), "overall_reasons": ["保真检查异常"]}
            validation.setdefault("errors", []).append(f"fidelity check failed: {exc}")

    # 4. Render and persist. Parts 0/2/3 are rendered from the JSON machine
    #    block, so Markdown and report.json cannot disagree.
    try:
        rendered = render_report_outputs(
            prose_markdown=prose_markdown + fidelity_appendix,
            parsed_json=parsed_json,
            prepare_result=prepare_result,
            output_dir=out_dir_path,
            base_name=file_base_name,
            validation=validation,
            fidelity=fidelity_result,
        )
    except Exception as exc:  # noqa: BLE001 - fail-closed on render errors
        validation.setdefault("errors", []).append(
            f"渲染产物异常（fail-closed）：{type(exc).__name__}: {exc}")
        validation["status"] = "failed"
        attach_repair(validation, prepare_result, parsed_json)
        return _failed_result(validation)

    # 5. Final artifact audit: no identity may survive into a public artifact.
    if meta.get("desensitize", True):
        final_leaks = _final_artifact_audit(rendered, prepare_result, meta)
        if final_leaks:
            for saved_key in ("report_md_path", "report_json_path",
                              "desensitization_map_path", "manifest_path"):
                path = rendered["files_saved"].get(saved_key)
                if path:
                    try:
                        Path(path).unlink()
                    except OSError:
                        pass
            validation["desensitization"] = "failed"
            validation.setdefault("errors", []).extend(
                f"终检-公开产物身份泄漏：{leak['reason']}" for leak in final_leaks)
            validation["status"] = "failed"
            attach_repair(validation, prepare_result, parsed_json)
            rejected_path = None
            if out_dir_path:
                out_dir_path.mkdir(parents=True, exist_ok=True)
                rejected_path = out_dir_path / f"{file_base_name}_rejected.md"
                _atomic_write_text(rejected_path, (
                    f"# 【已拒绝】{work_title} 风格能力报告\n\n"
                    f"> 本响应未通过技能终检，禁止作为正式产物使用。失败原因：\n"
                    + "\n".join(f"> - {error}" for error in validation["errors"])
                    + "\n\n> 隐私警告：本文件包含未脱敏的原始响应内容，仅限私有保存与排查，禁止公开分发。\n"
                ))
            return _failed_result(validation, str(rejected_path) if rejected_path else None)

    # 6. Optional standalone persona prompt.
    system_prompt = None
    if meta.get("generate_system_prompt", False) and parsed_json:
        system_prompt = build_system_prompt(
            report_json=rendered["report_json"],
            allow_author_identity=meta.get("allow_author_identity", False),
        )
        if out_dir_path:
            prompt_path = out_dir_path / f"{file_base_name}_system_prompt.txt"
            _atomic_write_text(prompt_path, system_prompt)
            rendered["files_saved"]["system_prompt_path"] = str(prompt_path)

    return {
        "report_content": rendered["full_markdown"],
        "report_json": rendered["report_json"],
        "report_path": rendered["files_saved"].get("report_md_path"),
        "report_json_path": rendered["files_saved"].get("report_json_path"),
        "desensitization_map_path": rendered["files_saved"].get("desensitization_map_path"),
        "rejected_path": None,
        "validation": validation,
        "fidelity": fidelity_result,
        "system_prompt": system_prompt,
        "files_saved": rendered["files_saved"],
        "status": (
            "passed"
            if validation["status"] == "passed"
            and (not fidelity_result or fidelity_result.get("status") == "passed")
            else "failed"
        ),
    }


# ---------------------------------------------------------------------------
# standalone helpers
# ---------------------------------------------------------------------------

def analyze_style(text: str) -> Dict[str, Any]:
    """Pure quantitative style analysis (no sampling, no LLM)."""
    return StyleAnalyzer().analyze(text)


def process_large_file(
    file_path: str | Path,
    budget_chars: int = 150000,
) -> Dict[str, Any]:
    """Index a large corpus and build the five-era stratified reading plan.

    Noise filtering runs up front so the chapter index and sampling range match
    the text ``prepare_analysis`` operates on, keeping this command on the same
    processing path as the full pipeline.
    """
    text, encoding = read_text_file(file_path)
    clean_text, noise_ratio, noise_stats = filter_noise(text)
    chapters, is_fallback = build_chapter_index(clean_text)
    plan = create_reading_plan(clean_text, chapters, budget_chars=budget_chars, is_fallback=is_fallback)
    return {
        "encoding": encoding,
        "total_chapters": len(chapters),
        "is_fallback": is_fallback,
        "noise_ratio": noise_ratio,
        "noise_ratio_pct": noise_stats.get("noise_ratio_pct", "0.00%"),
        "reading_plan": plan,
    }


# Backwards-compatible alias: the check now lives in report/health.py, but the
# name is part of the pre-10.2 surface and is cheap to keep.
def response_health_check(prose_markdown: str, prepare_result: Any = None) -> List[str]:
    """Deprecated alias for :func:`report.health.check_response_health`."""
    return check_response_health(prose_markdown)
