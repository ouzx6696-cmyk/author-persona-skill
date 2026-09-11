# -*- coding: utf-8 -*-
"""Chapter indexing and fallback equal-partitioning."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


VOLUME_PATTERN = re.compile(
    r'^\s*第[0-9零一二两三四五六七八九十百千万]+卷(?:[\s:：].*)?$', re.MULTILINE
)

CHAPTER_PATTERNS = [
    # Chinese chapter patterns: 第1章, 第一百二十章, 第1回, 第一节, 终章, 尾声, 序章, 楔子
    re.compile(r'^\s*(?:第[0-9零一二两三四五六七八九十百千万]+[章节回节折篇]|序章|楔子|尾声|终章|番外[0-9零一二两三四五六七八九十百千万]*)(?:[\s:：].*)?$', re.MULTILINE),
    # English patterns: Chapter 1, Act 1, Prologue, Epilogue
    re.compile(r'^\s*(?:Chapter|ACT|Volume|Book)\s+[0-9IVXLCDM]+(?:[\s:：].*)?$', re.IGNORECASE | re.MULTILINE),
]


def build_chapter_index(text: str, fallback_chunk_size: int = 4000) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Scan text to find chapter boundaries.
    Returns (chapter_list, is_fallback).
    """
    matches: List[Tuple[int, str]] = []

    for pat in CHAPTER_PATTERNS:
        for m in pat.finditer(text):
            matches.append((m.start(), m.group().strip()))

    # Sort matches by character position
    matches.sort(key=lambda x: x[0])

    # De-duplicate matches at the exact same position or overlapping lines
    deduped_matches: List[Tuple[int, str]] = []
    seen_positions = set()
    for pos, title in matches:
        if pos not in seen_positions:
            deduped_matches.append((pos, title))
            seen_positions.add(pos)

    # Volume headers for multi-volume books (e.g. 第一卷 ... / Volume 1)
    volume_spans: list[tuple[int, str]] = []
    for m in VOLUME_PATTERN.finditer(text):
        volume_spans.append((m.start(), m.group().strip()))
    volume_spans.sort(key=lambda x: x[0])

    def _volume_for(pos: int) -> str:
        cur = ""
        for vpos, vtitle in volume_spans:
            if vpos < pos:
                cur = vtitle
            else:
                break
        # keep only the "第X卷" prefix for brevity
        if cur:
            import re as _re
            mm = _re.match(r"\s*(第[0-9零一二两三四五六七八九十百千万]+卷)", cur)
            if mm:
                return mm.group(1)
        return cur

    total_len = len(text)
    chapters: List[Dict[str, Any]] = []

    # Canonical chapter model: chapter_idx is the only key used for era
    # arithmetic (0-based, half-open spans). chapter_no is display-only
    # (1-based), chapter_id is the stable cross-artifact key. `index` is kept
    # as an alias of chapter_no for compatibility.
    # If we found at least 2 chapters, use detected boundaries
    if len(deduped_matches) >= 2:
        for i in range(len(deduped_matches)):
            start_pos, title = deduped_matches[i]
            end_pos = deduped_matches[i + 1][0] if i + 1 < len(deduped_matches) else total_len
            chapters.append({
                "index": i + 1,
                "chapter_idx": i,
                "chapter_no": i + 1,
                "chapter_id": f"C{i + 1:04d}",
                "title": title,
                "volume": _volume_for(start_pos),
                "start": start_pos,
                "end": end_pos,
                "length": end_pos - start_pos,
            })
        return chapters, False

    # Fallback: Partition into virtual chapters of ~fallback_chunk_size
    is_fallback = True
    start = 0
    idx = 1
    while start < total_len:
        end = min(start + fallback_chunk_size, total_len)
        chapters.append({
            "index": idx,
            "chapter_idx": idx - 1,
            "chapter_no": idx,
            "chapter_id": f"C{idx:04d}",
            "title": f"分段_{idx:03d}",
            "start": start,
            "end": end,
            "length": end - start,
        })
        start = end
        idx += 1

    return chapters, is_fallback
