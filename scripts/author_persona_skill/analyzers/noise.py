# -*- coding: utf-8 -*-
"""Noise filtering engine: removes platform notes, watermarks, repetitive dividers, and corrupted text."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# Regex patterns for noise lines
PLATFORM_PATTERNS = [
    re.compile(r'^\s*(?:PS|ps|Ps|作者有话说|作者说|求月票|求推荐|求收藏|求订阅|月票|推荐票|加更|打赏|感谢|盟主|舵主|堂主|打赏补更|起点中文网|17K|纵横|晋江|番茄)[：: -].*$', re.IGNORECASE),
    re.compile(r'^\s*(?:最新章节|加入书签|投票推荐|上一章|下一章|返回目录|章节目录|本章完|全文完|（全书完）|\(全书完\)).*$', re.IGNORECASE),
    re.compile(r'.*https?://\S+.*', re.IGNORECASE),
    re.compile(r'.*(?:www\.\S+|bbs\.\S+).*', re.IGNORECASE),
]

STRUCTURAL_DIVIDERS = re.compile(r'^\s*[-=_*~]{4,}\s*$')
CORRUPTED_CHARS = re.compile(r'[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]')


def filter_noise(text: str) -> Tuple[str, float, Dict[str, Any]]:
    """
    Filter noise lines from raw corpus text.
    Returns:
        clean_text: Sanitized text
        noise_ratio: Noise characters / Total characters (0.0 to 1.0)
        stats: Detailed counts of removed lines by category
    """
    if not text:
        return "", 0.0, {"raw_chars": 0, "clean_chars": 0, "removed_lines": 0, "categories": {}}

    raw_chars = len(text)
    lines = text.splitlines(keepends=True)
    clean_lines: List[str] = []
    removed_chars = 0
    removed_lines = 0

    category_counts = {
        "platform_notes": 0,
        "watermarks": 0,
        "structural_dividers": 0,
        "corrupted_lines": 0,
    }

    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append(line)
            continue

        # Check corrupted chars
        if CORRUPTED_CHARS.search(line):
            cleaned_line = CORRUPTED_CHARS.sub('', line)
            if len(cleaned_line.strip()) < 2:
                removed_chars += len(line)
                removed_lines += 1
                category_counts["corrupted_lines"] += 1
                continue
            line = cleaned_line
            stripped = line.strip()

        # Check structural dividers
        if STRUCTURAL_DIVIDERS.match(stripped):
            removed_chars += len(line)
            removed_lines += 1
            category_counts["structural_dividers"] += 1
            continue

        # Check platform & watermark patterns
        is_noise = False
        for pat in PLATFORM_PATTERNS:
            if pat.match(stripped):
                is_noise = True
                removed_chars += len(line)
                removed_lines += 1
                if "PS" in stripped or "作者" in stripped or "票" in stripped or "打赏" in stripped:
                    category_counts["platform_notes"] += 1
                else:
                    category_counts["watermarks"] += 1
                break

        if not is_noise:
            clean_lines.append(line)

    clean_text = "".join(clean_lines)
    clean_chars = len(clean_text)
    noise_ratio = (removed_chars / raw_chars) if raw_chars > 0 else 0.0

    stats = {
        "raw_chars": raw_chars,
        "clean_chars": clean_chars,
        "removed_chars": removed_chars,
        "removed_lines": removed_lines,
        "noise_ratio": round(noise_ratio, 4),
        "noise_ratio_pct": f"{noise_ratio * 100:.2f}%",
        "categories": category_counts,
    }

    return clean_text, noise_ratio, stats
