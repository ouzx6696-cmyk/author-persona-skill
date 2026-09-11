# -*- coding: utf-8 -*-
"""Fidelity closed-loop verification: compares trial writing metrics against baseline features."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..analyzers.style_analyzer import StyleAnalyzer


_SCENE_SPLIT_RE = re.compile(r"^\s*(?:-{3,}|={3,}|#{1,6}\s*场景[^\n]*)\s*$", re.M)
# `# 场景…` 形态的分隔行自身携带类型标注（如 `# 场景2：冲突`），fidelity.md
# 允许这种写法，因此切分时归入下一场景首行而不是丢弃；`---`/`===` 无语义，仍丢弃。
_SCENE_HEADING_RE = re.compile(r"^#{1,6}\s*场景")
_SCENE_TYPE_KEYWORDS = {
    "日常": ("日常", "互动", "探索"),
    "冲突": ("冲突", "打斗", "高压", "战斗"),
    "抉择": ("抉择", "危机", "关键", "决定"),
}


def split_trial_scenes(trial_text: "str | List[str]") -> List[str]:
    """把试写文本切分为场景：单独一行 ``---`` / ``===`` / ``# 场景…`` 为分隔符。

    ``# 场景…`` 分隔行保留为下一场景首行，使 ``scene_type_coverage`` 能读到
    场景头 40 字内的类型标注。
    """
    if isinstance(trial_text, list):
        parts = [str(p) for p in trial_text]
    else:
        text = str(trial_text)
        parts: List[str] = []
        pending_heading = ""
        last = 0
        for match in _SCENE_SPLIT_RE.finditer(text):
            segment = text[last:match.start()]
            delimiter = match.group(0).strip()
            if segment.strip() or parts or pending_heading:
                parts.append(f"{pending_heading}\n{segment}" if pending_heading else segment)
            pending_heading = delimiter if _SCENE_HEADING_RE.match(delimiter) else ""
            last = match.end()
        tail = text[last:]
        parts.append(f"{pending_heading}\n{tail}" if pending_heading else tail)
    return [p.strip() for p in parts if p and p.strip()]


def check_trial_scene_requirements(scenes: List[str]) -> List[str]:
    """fidelity.md 的场景要求：2–3 个场景、每个 ≥800 字。"""
    issues: List[str] = []
    if not (2 <= len(scenes) <= 3):
        issues.append(
            f"试写场景数应为 2–3 个（用单独一行 '---' 分隔场景），实际 {len(scenes)} 个"
        )
    for index, scene in enumerate(scenes, 1):
        if len(scene) < 800:
            issues.append(f"场景 {index} 不足 800 字（实际 {len(scene)} 字）")
    return issues


def scene_type_coverage(scenes: List[str]) -> Optional[List[str]]:
    """按场景开头关键词识别类型；全部未标注时返回 None（不判定类型覆盖）。"""
    labels: List[Optional[str]] = []
    for scene in scenes:
        head = scene[:40]
        label = None
        for type_name, keywords in _SCENE_TYPE_KEYWORDS.items():
            if any(k in head for k in keywords):
                label = type_name
                break
        labels.append(label)
    if all(l is None for l in labels):
        return None
    return [t for t in ("日常", "冲突", "抉择") if t not in labels]


def measure_scenes(scenes: List[str]) -> List[Dict[str, Any]]:
    """分场景摘要指标（信息性，不参与通过/失败判定）。"""
    analyzer = StyleAnalyzer()
    rows: List[Dict[str, Any]] = []
    for index, scene in enumerate(scenes, 1):
        metrics = analyzer.analyze(scene)
        rows.append({
            "scene": index,
            "chars": len(scene),
            "avg_sent_len": metrics.get("sentence_structure", {}).get("avg_sent_len"),
            "dialogue_ratio_pct": metrics.get("dialogue_features", {}).get("dialogue_ratio_pct"),
        })
    return rows


DEFAULT_TOLERANCES = {
    "avg_sent_len_pct": 0.15,       # ±15%
    "dialogue_ratio_diff": 0.10,     # ±10 percentage points
    "short_sent_ratio_diff": 0.10,   # ±10 percentage points
    "metaphor_density_pct": 0.30,    # ±30%
}


def median_mad_band(values: List[float], k: float = 3.0) -> Tuple[float, float, float]:
    """Dynamic tolerance: median ± k*MAD (robust to non-normal prose)."""
    if not values:
        return 0.0, 0.0, 0.0
    s = sorted(values)
    n = len(s)
    median = float(s[n // 2]) if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    deviations = sorted(abs(v - median) for v in s)
    mad = float(deviations[n // 2]) if n % 2 == 1 else (
        deviations[n // 2 - 1] + deviations[n // 2]) / 2.0
    if mad == 0:
        mad = abs(median) * 0.05 or 0.5
    return median, max(0.0, median - k * mad), median + k * mad


def derive_dynamic_tolerances(window_metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive author-specific bands from W1..Wn window metrics.

    Input: list of per-window StyleAnalyzer outputs. Output: {metric: (lo, hi)}.
    Falls back to DEFAULT_TOLERANCES when windows are absent (backward compat).
    """
    if not window_metrics or len(window_metrics) < 4:
        return {}
    def _collect(path: Tuple[str, str]) -> List[float]:
        out = []
        for w in window_metrics:
            try:
                v = w
                for p in path:
                    v = v.get(p, {})
                out.append(float(v))
            except (TypeError, ValueError, AttributeError):
                continue
        return out
    bands: Dict[str, Any] = {}
    for key, path in {
        "avg_sent_len": ("sentence_structure", "avg_sent_len"),
        "dialogue_ratio": ("dialogue_features", "dialogue_ratio"),
        "short_sent_ratio": ("sentence_structure", "short_sent_ratio"),
        "metaphor_density": ("rhetoric_features", "metaphor_density"),
    }.items():
        vals = _collect(path)
        if len(vals) >= 4:
            med, lo, hi = median_mad_band(vals)
            bands[key] = {"median": med, "lo": lo, "hi": hi}
    return bands


def ngram_overlap_ratio(trial: str, reference: str, n: int = 5) -> float:
    """Character n-gram overlap ratio (trial n-grams found in reference)."""
    if len(trial) < n or len(reference) < n:
        return 0.0
    ref_set = {reference[i:i + n] for i in range(len(reference) - n + 1)}
    if not ref_set:
        return 0.0
    hits = sum(1 for i in range(len(trial) - n + 1) if trial[i:i + n] in ref_set)
    return hits / max(1, len(trial) - n + 1)


def longest_common_substring_len(a: str, b: str, limit: int = 2000) -> int:
    """Bounded LCS length (DP on truncated inputs to stay stdlib-cheap)."""
    a, b = a[:limit], b[:limit]
    if not a or not b:
        return 0
    # Use shorter string for DP width
    if len(a) < len(b):
        a, b = b, a
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ca = a[i - 1]
        for j in range(1, len(b) + 1):
            if ca == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def check_copy_risk(
    trial_text: str,
    reference_texts: Optional[List[str]] = None,
    lcs_threshold: int = 40,
    five_gram_threshold: float = 0.35,
) -> Dict[str, Any]:
    """'不是抄出来的'检测:高保真不能是高复制.

    reference_texts: evidence chunk texts (private, never rendered public).
    Returns {is_copy_risk, longest_match, five_gram_overlap, reason}.
    """
    refs = [r for r in (reference_texts or []) if r]
    if not refs or not trial_text:
        return {"is_copy_risk": False, "longest_match": 0,
                "five_gram_overlap": 0.0, "reason": "无参照文本,跳过复制检测"}
    combined_ref = "\n".join(refs)[:20000]
    trial = trial_text[:20000]
    lcs = longest_common_substring_len(trial, combined_ref)
    ov5 = ngram_overlap_ratio(trial, combined_ref, 5)
    ov7 = ngram_overlap_ratio(trial, combined_ref, 7)
    # Short probes (<200 chars) make n-gram ratios noisy; require LCS for them.
    if len(trial) < 200:
        is_risk = lcs >= lcs_threshold
    else:
        is_risk = (lcs >= lcs_threshold) or (ov5 >= five_gram_threshold and ov7 >= 0.15)
    reason = ""
    if is_risk:
        reason = (f"与原文连续一致 {lcs} 字(阈值{lcs_threshold})"
                  f"/5-gram重叠{ov5:.2f},疑似复现原文")
    return {"is_copy_risk": is_risk, "longest_match": lcs,
            "five_gram_overlap": round(ov5, 3),
            "seven_gram_overlap": round(ov7, 3), "reason": reason}


def evaluate_card_in_text(
    card: Dict[str, Any],
    text: str,
    reference_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Evaluate a card using explicit, explainable surface markers.

    This is intentionally conservative: an unknown card is not automatically
    considered covered merely because the trial is long enough.

    Dialogue_tag / perspective / rhythm profiles keep viewpoint and
    structural cards from falling back to not_applicable. Reference-aware
    checks (tag distribution vs measured) apply when reference_metrics given.
    """
    if not isinstance(card, dict):
        return {"id": "T00", "name": "未命名技法", "status": "not_applicable", "notes": "卡片不是对象"}

    cid = str(card.get("id", "T00"))
    name = str(card.get("name", "未命名技法"))
    body = " ".join([name, str(card.get("definition", "")), *[str(s) for s in card.get("steps", [])]])
    profile = None
    markers: List[str] = []
    if any(term in body for term in ("比喻", "点染", "喻体")):
        profile = "metaphor"
        markers = ["宛若", "仿佛", "如同", "犹如", "像", "如"]
    elif any(term in body for term in ("动作", "推拉", "切分", "动词")):
        profile = "action"
        markers = ["拔", "斩", "冲", "退", "出拳", "踏", "抓", "挥"]
    elif any(term in body for term in ("设问", "线索", "疑问", "反问")):
        profile = "question"
        markers = ["难道", "为何", "究竟", "？", "?"]
    elif any(term in body for term in ("省略号", "悬置")):
        profile = "ellipsis"
        markers = ["……", "..."]
    elif any(term in body for term in ("破折号", "揭底")):
        profile = "dash"
        markers = ["——", "--"]
    elif any(term in body for term in ("对话标签", "标签", "说话人", "对白", "台词", "声纹", "口癖")):
        profile = "dialogue_tag"
        markers = ["说道", "问道", "答道", "笑道", "说", "道", "问", "\u201c", "\u201d", "「", "」"]
    elif any(term in body for term in ("视角", "人称", "镜头", "景别", "限知", "全知")):
        profile = "perspective"
        markers = ["他", "她", "我", "你"]
    elif any(term in body for term in ("节奏", "段落", "换行", "收束", "转场", "留白", "悬念", "节拍")):
        profile = "rhythm"
        markers = []  # structural: checked via line breaks below

    if profile is None:
        return {"id": cid, "name": name, "status": "not_applicable", "notes": "无法从卡片定义推导可执行检测特征"}

    # rhythm is structural: short-para hammer or explicit line-break breathing
    if profile == "rhythm":
        paras = [p for p in text.splitlines() if p.strip()]
        short_paras = [p for p in paras if len(p.strip()) <= 8]
        if short_paras or len(paras) >= 3:
            return {"id": cid, "name": name, "status": "covered",
                    "notes": f"检测到段落呼吸结构：{len(paras)}段/极短段{len(short_paras)}"}
        return {"id": cid, "name": name, "status": "uncovered",
                "notes": "未检测到段落节奏结构（换行/极短段）"}

    hits = [marker for marker in markers if marker in text]
    if not hits:
        status = "uncovered"
        notes = "未检测到该技法的核心行文标记"
    else:
        status = "covered"
        notes = f"检测到核心行文标记：{'、'.join(hits[:3])}"
        if profile == "ellipsis" and text.count("……") > max(3, len(text) // 350):
            status = "deformed"
            notes = "省略号密度明显过高，技法发生退化"
        elif profile == "dash" and text.count("——") > max(3, len(text) // 350):
            status = "deformed"
            notes = "破折号密度明显过高，技法发生退化"
        elif profile == "dialogue_tag" and reference_metrics:
            # reference-aware: main tag must survive in trial
            try:
                freqs = (reference_metrics.get("dialogue_features", {})
                         .get("tag_frequencies", {}))
                if isinstance(freqs, dict) and freqs:
                    top = max(freqs, key=lambda k: freqs[k])
                    if top and top not in text:
                        status = "uncovered"
                        notes = f"主力对话标签「{top}」在试写中缺失"
            except Exception:
                pass

    return {"id": cid, "name": name, "status": status, "notes": notes}


def _metric_at(metrics: Dict[str, Any], path: Tuple[str, str]) -> Optional[float]:
    node: Any = metrics
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


# 偏差表由这张规格表生成：固定容差、展示格式与动态区间覆写共用同一份定义，
# 三者不会各自漂移（历史 bug：动态区间只覆写了平均句长一项）。
_DEVIATION_SPECS = (
    {
        "key": "avg_sent_len",
        "label": "平均句长 (avg_sent_len)",
        "path": ("sentence_structure", "avg_sent_len"),
        "mode": "pct",
        "tol_key": "avg_sent_len_pct",
        "fmt": "{:.1f} 字",
        "scale": 1.0,
        "skip_if_zero": True,
    },
    {
        "key": "short_sent_ratio",
        "label": "短句率 (short_sent_ratio)",
        "path": ("sentence_structure", "short_sent_ratio"),
        "mode": "pt",
        "tol_key": "short_sent_ratio_diff",
        "fmt": "{:.1f}%",
        "scale": 100.0,
    },
    {
        "key": "dialogue_ratio",
        "label": "对话字符占比 (dialogue_ratio)",
        "path": ("dialogue_features", "dialogue_ratio"),
        "mode": "pt",
        "tol_key": "dialogue_ratio_diff",
        "fmt": "{:.1f}%",
        "scale": 100.0,
    },
    {
        "key": "metaphor_density",
        "label": "比喻密度 (metaphor_density)",
        "path": ("rhetoric_features", "metaphor_density"),
        "mode": "pct",
        "tol_key": "metaphor_density_pct",
        "fmt": "{:.2f} /千字",
        "scale": 1.0,
        "skip_if_zero": True,
    },
)


def compute_metric_deviations(
    trial_metrics: Dict[str, Any],
    ref_metrics: Dict[str, Any],
    tolerances: Optional[Dict[str, float]] = None,
    dynamic_bands: Optional[Dict[str, Dict[str, float]]] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Compute deviation table between trial text and baseline reference metrics.

    ``dynamic_bands`` (from :func:`derive_dynamic_tolerances`) win over the fixed
    tolerance whenever the trial value sits inside the author's own window
    distribution: prose inside the author's natural range is not a fidelity
    failure just because it left a hardcoded percentage band. Every metric with a
    band is covered — the fixed table and the band override share one spec list.
    """
    tol = dict(DEFAULT_TOLERANCES)
    if tolerances:
        tol.update(tolerances)
    bands = dynamic_bands or {}
    deviations: List[Dict[str, Any]] = []
    all_passed = True

    for spec in _DEVIATION_SPECS:
        ref = _metric_at(ref_metrics, spec["path"])
        trial = _metric_at(trial_metrics, spec["path"])
        if ref is None or trial is None:
            continue
        if spec.get("skip_if_zero") and ref <= 0:
            continue

        limit = float(tol[spec["tol_key"]])
        band = bands.get(spec["key"]) or {}
        try:
            in_band = float(band["lo"]) <= trial <= float(band["hi"])
        except (KeyError, TypeError, ValueError):
            in_band = False

        if spec["mode"] == "pct":
            deviation = abs(trial - ref) / ref
            deviation_text = f"{deviation * 100:.1f}%"
            threshold_text = f"±{limit * 100:.0f}%"
        else:
            deviation = abs(trial - ref)
            deviation_text = f"{deviation * spec['scale']:.1f} pt"
            threshold_text = f"±{limit * 100:.0f} pt"
        if in_band:
            threshold_text += "（作者自然波动区间内）"

        passed = deviation <= limit or in_band
        if not passed:
            all_passed = False
        deviations.append({
            "key": spec["key"],
            "metric": spec["label"],
            "reference": spec["fmt"].format(ref * spec["scale"]),
            "trial": spec["fmt"].format(trial * spec["scale"]),
            "deviation": deviation_text,
            "threshold": threshold_text,
            "status": "passed" if passed else "failed",
            "basis": "author_band" if in_band else "fixed_tolerance",
        })

    return deviations, all_passed


def run_fidelity_check(
    trial_text: str | List[str],
    reference_metrics: Dict[str, Any],
    technique_cards: Optional[List[Dict[str, Any]]] = None,
    tolerances: Optional[Dict[str, float]] = None,
    reference_texts: Optional[List[str]] = None,
    window_metrics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Evaluate trial written text fidelity against quantitative benchmark and technique cards.

    Also reports multi-probe per-scene summary, copy-risk detection
    (SOURCE_OVERLAP_TOO_HIGH), and dynamic MAD bands when window_metrics are
    supplied. Core pass/fail = metrics + applicable cards + copy check.
    """
    combined_text = "\n\n".join(trial_text) if isinstance(trial_text, list) else trial_text

    # 场景强制校验（2–3 个场景、每个 ≥800 字、标注时类型覆盖）与 finalize
    # 路径同源：finalize 与独立 CLI 调用走的是同一入口，不再出现
    # 「独立调用恒 PASSED」的双路径分叉。
    scenes = split_trial_scenes(trial_text)
    scene_issues = check_trial_scene_requirements(scenes)
    missing_types = scene_type_coverage(scenes)
    if missing_types:
        scene_issues = scene_issues + [
            f"场景类型未覆盖：{'、'.join(missing_types)}（在场景开头标注 日常/冲突/抉择）"
        ]

    analyzer = StyleAnalyzer()
    trial_metrics = analyzer.analyze(combined_text)

    # Dynamic MAD bands tighten/loosen the fixed tolerances when the author's
    # per-era window distribution is available (prepare supplies it).
    dynamic_bands = derive_dynamic_tolerances(window_metrics or [])
    deviations, metrics_passed = compute_metric_deviations(
        trial_metrics=trial_metrics,
        ref_metrics=reference_metrics,
        tolerances=tolerances,
        dynamic_bands=dynamic_bands,
    )

    card_evaluations = [evaluate_card_in_text(card, combined_text, reference_metrics)
                        for card in (technique_cards or [])]
    blocking_cards = [
        item for item in card_evaluations
        if item.get("status") in {"uncovered", "deformed"}
    ]
    applicable_cards = [item for item in card_evaluations if item.get("status") != "not_applicable"]
    cards_passed = not blocking_cards
    # Multi-probe per-scene summary (2-3 scenes required by finalize;
    # 5-probe ideal: 日常/冲突/抉择/描写/混合 -- report pass rate and
    # surface it for the appendix).
    probe_rows = measure_scenes(scenes)
    probe_summary = {
        "total": len(probe_rows),
        "adequate": sum(1 for row in probe_rows if row.get("chars", 0) >= 800),
        "detail": probe_rows,
    }
    # Copy-risk gate (high fidelity must not be plagiarism).
    copy_info = check_copy_risk(combined_text, reference_texts or [])
    copy_passed = not copy_info.get("is_copy_risk", False)
    scene_passed = not scene_issues
    overall_status = (
        "passed" if (metrics_passed and cards_passed and copy_passed and scene_passed) else "failed"
    )
    reasons: List[str] = []
    if not metrics_passed:
        reasons.append("定量指标未通过容差校验")
    if blocking_cards:
        reasons.append("存在未覆盖或走样的适用技法卡：" + ", ".join(item["id"] for item in blocking_cards))
    if not copy_passed:
        reasons.append("SOURCE_OVERLAP_TOO_HIGH：" + str(copy_info.get("reason", "")))
    reasons.extend(scene_issues)

    return {
        "status": overall_status,
        "fidelity": overall_status,
        "metrics_passed": metrics_passed,
        "cards_passed": cards_passed,
        "copy_passed": copy_passed,
        "scene_requirements": {"scene_count": len(scenes), "issues": scene_issues},
        "copy_check": copy_info,
        "probe_summary": probe_summary,
        "dynamic_bands": dynamic_bands,
        "metrics_status": "passed" if metrics_passed else "failed",
        "card_summary": {"total": len(card_evaluations), "applicable": len(applicable_cards), "blocking": len(blocking_cards)},
        "overall_reasons": reasons,
        "deviations_table": deviations,
        "technique_card_evaluations": card_evaluations,
        "trial_metrics": trial_metrics,
    }
