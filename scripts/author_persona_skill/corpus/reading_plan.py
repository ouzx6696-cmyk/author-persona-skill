# -*- coding: utf-8 -*-
"""5-era stratified reading plan and sampling strategy."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_CHAPTER_NUM_RE = re.compile(r"[0-9零一二两三四五六七八九十百千万零〇两]+")


def _chapter_label(chapter: Dict[str, Any]) -> Tuple[str, str]:
    """
    Prefer the chapter number printed in the title (第0001章/第一百二十章)
    over the positional index. Volume comes from chapter_index so ranges stay
    unambiguous when per-volume chapter numbering resets.
    """
    title = str(chapter.get("title", ""))
    vol = str(chapter.get("volume", "")).strip()
    num = ""
    if "章" in title or "回" in title or "节" in title:
        m = _CHAPTER_NUM_RE.search(title)
        if m and m.group(0):
            num = m.group(0)
    if not num:
        # prefer canonical chapter_no, fall back to index
        num = str(chapter.get("chapter_no", chapter.get("index", "?")))
    return vol, num


def _era_range_desc(first: Dict[str, Any], last: Dict[str, Any]) -> str:
    """Human-readable range that stays unambiguous for multi-volume books."""
    v1, n1 = _chapter_label(first)
    v2, n2 = _chapter_label(last)
    if v1 and v1 == v2:
        return f"{v1} 第{n1}~{n2}章"
    if v1 or v2:
        left = f"{v1}·第{n1}章" if v1 else f"第{n1}章"
        right = f"{v2}·第{n2}章" if v2 else f"第{n2}章"
        return f"{left} ~ {right}"
    return f"第{n1}~{n2}章"


# Era labels used when the whole book is sampled. Short corpora cannot support
# five eras, so the label set shrinks while always keeping an opening and an
# ending -- otherwise small inputs would have no era dimension at all and the
# cross-era evidence gate would silently degrade to not_applicable.
#
# Every era has a stable era_id (ERA_1..ERA_5). Human label stays for
# display, era_id is the machine key used by evidence/metric/claim stores.
_ERA_NAMES_BY_COUNT: Dict[int, Tuple[str, ...]] = {
    1: ("开头 (Begin)",),
    2: ("开头 (Begin)", "结尾 (Ending)"),
    3: ("开头 (Begin)", "成熟 (Mature)", "结尾 (Ending)"),
    4: ("开头 (Begin)", "发展 (Develop)", "演变 (Evolve)", "结尾 (Ending)"),
    5: ("开头 (Begin)", "发展 (Develop)", "成熟 (Mature)", "演变 (Evolve)", "结尾 (Ending)"),
}

_FULL_ERA_IDS = ("ERA_1", "ERA_2", "ERA_3", "ERA_4", "ERA_5")
_ERA_LABEL_TO_ID = {
    "开头 (Begin)": "ERA_1",
    "发展 (Develop)": "ERA_2",
    "成熟 (Mature)": "ERA_3",
    "演变 (Evolve)": "ERA_4",
    "结尾 (Ending)": "ERA_5",
}


def era_id_for_label(label: str) -> str:
    return _ERA_LABEL_TO_ID.get(str(label).strip(), "")


def _chapter_idx_of(ch: Dict[str, Any]) -> int:
    """Canonical positional key. Prefers chapter_idx, falls back to index-1."""
    if "chapter_idx" in ch:
        try:
            return int(ch["chapter_idx"])
        except (TypeError, ValueError):
            pass
    try:
        return int(ch.get("index", 1)) - 1
    except (TypeError, ValueError):
        return 0


def _chapter_key_of(ch: Dict[str, Any]) -> int:
    """Dedup key: chapter_id preferred, else chapter_idx, else index."""
    if ch.get("chapter_id"):
        return hash(str(ch["chapter_id"]))
    return _chapter_idx_of(ch)


def validate_era_invariants(chapters: List[Dict[str, Any]], era_ranges: List[Tuple[str, int, int]]) -> None:
    """Fail-closed invariants: every chapter belongs to at least one era.

    NOTE: era_ranges use max(+1) guards so adjacent spans may overlap
    by one chapter on tiny inputs (first-win via setdefault). Coverage (no
    chapter left unassigned) is the enforced invariant; per-chapter
    assignment in index_to_era is first-win and deterministic, keyed by
    chapter_idx -- looking it up by the 1-based display index would shift
    every boundary by one and strand the last chapter.
    """
    total = len(chapters)
    covered = set()
    for _label, s, e in era_ranges:
        assert 0 <= s <= e <= total, f"era span out of range: {(s, e)} vs N={total}"
        for i in range(s, e):
            covered.add(i)
    assert len(covered) == total, f"era coverage {len(covered)} != chapters {total}"


def _era_names(count: int) -> Tuple[str, ...]:
    """Return a spread of era labels for ``count`` eras (max 5)."""
    if count <= 0:
        return ()
    return _ERA_NAMES_BY_COUNT[min(count, 5)]


def create_reading_plan(
    text: str,
    chapters: List[Dict[str, Any]],
    budget_chars: int = 150000,
    is_fallback: bool = False,
) -> Dict[str, Any]:
    """
    Generate a 5-era stratified sampling reading plan.
    """
    total_chars = len(text)
    total_chapters = len(chapters)

    # If text is small enough, take everything.
    # Era labels are still assigned here: leaving chapters unlabeled made every
    # chunk fall into "未分期", which turned the cross-era evidence requirement
    # into a not_applicable warning instead of a real gate for short corpora.
    if total_chars <= budget_chars or total_chapters <= 5:
        era_names = _era_names(total_chapters)
        labeled_chapters: List[Dict[str, Any]] = []
        if era_names:
            # 按比例切分（idx * n // total），余数逐段摊到前面的时期。
            # 早先用 floor(group_size) + 末段吸收余数：7 章时"结尾"占 3 章、
            # 9 章时占 5 章，时期长度失衡会让证据池与跨期归纳被末期样本主导，
            # 也与长语料路径的百分比切分语义不一致。
            n_eras = len(era_names)
            for idx, ch in enumerate(chapters):
                era = era_names[min(idx * n_eras // total_chapters, n_eras - 1)]
                labeled_chapters.append({**ch, "era": era, "era_id": era_id_for_label(era)})
        else:
            labeled_chapters = list(chapters)

        era_coverage: Dict[str, str] = {}
        for era in era_names:
            members = [c for c in labeled_chapters if c.get("era") == era]
            if not members:
                continue
            range_txt = _era_range_desc(members[0], members[-1])
            era_coverage[era] = f"{era} 分段 {range_txt}" if is_fallback else f"{era} {range_txt}"

        return {
            "sampled_text": text,
            "sampled_chapters": labeled_chapters,
            "sample_range_desc": f"全书采样（共 {total_chapters} 章节/分段，{total_chars:,} 字符，覆盖率 100%）",
            "coverage_pct": 100.0,
            "era_coverage": era_coverage or {"all": f"全书共 {total_chapters} 章节"},
            "era_ranges": [
                {"era": e, "era_id": era_id_for_label(e), "start_idx": 0, "end_idx": total_chapters}
                for e in era_names
            ],
        }

    # Divide into 5 eras
    # Per era budget roughly = budget_chars / 5
    if budget_chars <= 0:
        raise ValueError("budget_chars 必须为正整数。")
    per_era_budget = budget_chars // 5

    era_ranges = [
        ("开头 (Begin)", 0, max(1, int(total_chapters * 0.15))),
        ("发展 (Develop)", int(total_chapters * 0.15), max(int(total_chapters * 0.15) + 1, int(total_chapters * 0.40))),
        ("成熟 (Mature)", int(total_chapters * 0.40), max(int(total_chapters * 0.40) + 1, int(total_chapters * 0.65))),
        ("演变 (Evolve)", int(total_chapters * 0.65), max(int(total_chapters * 0.65) + 1, int(total_chapters * 0.85))),
        ("结尾 (Ending)", int(total_chapters * 0.85), total_chapters),
    ]

    # era 由章节位置区间决定,与"该章被哪个时期选中"无关:
    # 相邻时期借章凑数时不再互相污染 era 归属.
    # Era lookup is keyed by chapter_idx (0-based). Using the 1-based display
    # index here would shift every boundary by one and strand the last chapter.
    validate_era_invariants(chapters, era_ranges)
    index_to_era: Dict[int, str] = {}
    idx_to_era_id: Dict[int, str] = {}
    for era_name, start_idx, end_idx in era_ranges:
        for i in range(start_idx, end_idx):
            index_to_era.setdefault(i, era_name)
            idx_to_era_id.setdefault(i, era_id_for_label(era_name))

    sampled_chapters: List[Dict[str, Any]] = []

    for era_name, start_idx, end_idx in era_ranges:
        era_chaps = chapters[start_idx:end_idx]
        if not era_chaps:
            continue

        selected_in_era: List[Dict[str, Any]] = []
        accumulated_chars = 0

        # For Begin era, pick from the start; for Ending era, pick towards the end; for others pick from mid
        if "Begin" in era_name or "开头" in era_name:
            start_pick = 0
        elif "Ending" in era_name or "结尾" in era_name:
            start_pick = max(0, len(era_chaps) - 2)
        else:
            start_pick = len(era_chaps) // 2

        # Try picking at least 2 chapters
        for ch in era_chaps[start_pick:]:
            selected_in_era.append(dict(ch))
            accumulated_chars += ch["length"]
            if accumulated_chars >= per_era_budget and len(selected_in_era) >= 2:
                break

        if len(selected_in_era) < 2 and len(era_chaps) >= 2:
            # Add backwards if not enough
            for ch in reversed(era_chaps[:start_pick]):
                selected_in_era.insert(0, dict(ch))
                accumulated_chars += ch["length"]
                if len(selected_in_era) >= 2:
                    break

        # 预算是软目标：允许最多 1.5 倍溢出；超出时整章回退（保底 2 章），
        # Begin 保留开篇锚点、Ending 保留结尾锚点。单章超长且无法再裁时允许溢出。
        cap = per_era_budget + per_era_budget // 2
        if accumulated_chars > cap:
            if "Ending" in era_name or "结尾" in era_name:
                victim_order = list(range(len(selected_in_era) - 2, -1, -1))
            else:
                victim_order = list(range(len(selected_in_era) - 1, 0, -1))
            for victim in victim_order:
                if accumulated_chars <= cap or len(selected_in_era) <= 2:
                    break
                accumulated_chars -= selected_in_era[victim]["length"]
                del selected_in_era[victim]

        sampled_chapters.extend(selected_in_era)

    # Deduplicate and sort by canonical chapter position
    seen_keys = set()
    deduped_chaps: List[Dict[str, Any]] = []
    for ch in sampled_chapters:
        key = ch.get("chapter_id") or _chapter_idx_of(ch)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_chaps.append(ch)
    deduped_chaps.sort(key=lambda x: _chapter_idx_of(x))

    # era 以真实章节位置区间回填:借来的章保持其本来时期
    for ch in deduped_chaps:
        cidx = _chapter_idx_of(ch)
        ch["era"] = index_to_era.get(cidx, ch.get("era", "未分期"))
        ch["era_id"] = idx_to_era_id.get(cidx, ch.get("era_id", ""))
        if "chapter_idx" not in ch:
            ch["chapter_idx"] = cidx
        if "chapter_id" not in ch:
            ch["chapter_id"] = f"C{cidx + 1:04d}"

    # Slice text and recompute local chapter offsets for sampled_text
    sampled_text_parts = []
    local_chapters: List[Dict[str, Any]] = []
    current_local_pos = 0
    total_sampled_chars = 0

    for i, ch in enumerate(deduped_chaps):
        part = text[ch["start"]:ch["end"]]
        part_len = len(part)
        sampled_text_parts.append(part)
        total_sampled_chars += part_len

        local_ch = dict(ch)
        local_ch["orig_start"] = ch["start"]
        local_ch["orig_end"] = ch["end"]
        local_ch["start"] = current_local_pos
        local_ch["end"] = current_local_pos + part_len
        local_chapters.append(local_ch)

        # "\n\n" separator length is 2
        current_local_pos += part_len + 2

    sampled_text = "\n\n".join(sampled_text_parts)
    # 与 style_analyzer 的 total_chars 口径对齐：采样长度按实际分析文本计（含章节分隔符），
    # 否则采样描述里的字符数与报告定量层的 total_chars 会差 2×(章节数-1) 而对不上。
    total_sampled_chars = len(sampled_text)
    coverage_pct = round((total_sampled_chars / max(total_chars, 1)) * 100, 2)

    era_descriptions: List[str] = []
    era_coverage: Dict[str, str] = {}
    for era_name, _start_idx, _end_idx in era_ranges:
        members = [c for c in deduped_chaps if c.get("era") == era_name]
        if not members:
            continue
        range_txt = _era_range_desc(members[0], members[-1])
        desc = f"{era_name} {range_txt}" if not is_fallback else f"{era_name} 分段 {range_txt}"
        era_descriptions.append(desc)
        era_coverage[era_name] = desc

    sample_range_desc = " + ".join(era_descriptions) + f"（共采样 {len(deduped_chaps)} 章节，{total_sampled_chars:,} 字符，全书占比 {coverage_pct}%）"

    return {
        "sampled_text": sampled_text,
        "sampled_chapters": local_chapters,
        "sample_range_desc": sample_range_desc,
        "coverage_pct": coverage_pct,
        "era_coverage": era_coverage,
        "era_ranges": [
            {"era": n, "era_id": era_id_for_label(n), "start_idx": s, "end_idx": e}
            for n, s, e in era_ranges
        ],
    }
