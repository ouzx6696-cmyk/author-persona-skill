# -*- coding: utf-8 -*-
"""Structural health check on the raw LLM response.

Runs before schema validation and exists to catch the failure modes that a
schema check cannot see: a truncated response, a mock/template response, or a
response whose four-part skeleton is missing. Every issue here is a blocking
error; the schema/evidence/privacy/numeric gates come afterwards.
"""
from __future__ import annotations

import re
from typing import List

#: Minimum body length for the whole prose section. Below this the response is
#: treated as truncated or templated rather than merely thin.
MIN_PROSE_CHARS = 1000

#: The quantitative layer has a fixed 11-section contract; checking each heading
#: prevents a long but hollow response from passing the coarse four-part check.
#: The per-section minimum only enforces a non-empty body at runtime
#: (see references/report-schema.md); the 120-250 char causal-diagnosis depth is
#: a production quality target, not a blocker.
MIN_SECTION_BODY_CHARS = 5

SECTION_NUMBERS = tuple(range(1, 12))

_PART_HEADING_RES = {
    "第〇部分": re.compile(r"^##\s*[^\n]*第〇部分[^\n]*$", re.M),
    "第一部分": re.compile(r"^##\s*[^\n]*第一部分[^\n]*$", re.M),
    "第二部分": re.compile(r"^##\s*[^\n]*第二部分[^\n]*$", re.M),
    "第三部分": re.compile(r"^##\s*[^\n]*第三部分[^\n]*$", re.M),
}

_SECTION_HEADING_RE = re.compile(r"^###\s+1\.(\d+)\b[^\n]*\n", re.MULTILINE)


def check_response_health(prose_markdown: str) -> List[str]:
    """Return blocking structural errors for the prose half of a response.

    Line-level ``##`` matching is deliberate: a wide substring match once let
    ``**第二部分：…**`` through as a heading, after which single-source
    rendering silently fell back to the LLM's own text and the public report
    carried two contradictory copies of Part 2.
    """
    errors: List[str] = []
    prose_markdown = prose_markdown or ""

    for part, heading_re in _PART_HEADING_RES.items():
        if not heading_re.search(prose_markdown):
            errors.append(f"响应缺少必需的行级标题（## 开头）：{part}")

    section_matches = list(_SECTION_HEADING_RE.finditer(prose_markdown))
    found = {int(match.group(1)) for match in section_matches}
    missing = sorted(set(SECTION_NUMBERS) - found)
    if missing:
        errors.append(f"第一部分缺少小节：{', '.join(f'1.{n}' for n in missing)}")
    for index, match in enumerate(section_matches):
        section_no = int(match.group(1))
        if index + 1 < len(section_matches):
            end = section_matches[index + 1].start()
        else:
            end = prose_markdown.find("## 第二部分", match.end())
        if end < 0:
            end = len(prose_markdown)
        body = prose_markdown[match.end():end].strip()
        if len(body) < MIN_SECTION_BODY_CHARS:
            errors.append(
                f"第一部分 1.{section_no} 正文为空或过短"
                f"（{len(body)} < {MIN_SECTION_BODY_CHARS} 字符）"
            )

    if len(prose_markdown.strip()) < MIN_PROSE_CHARS:
        errors.append(
            f"正文长度不足（{len(prose_markdown.strip())} < {MIN_PROSE_CHARS} 字符），疑似模板/截断输出"
        )
    return errors
