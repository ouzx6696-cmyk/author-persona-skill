# -*- coding: utf-8 -*-
"""Writer Contract (Part 0) definitions, schema validation, and rendering.

第〇部分「作家定义与读者契约」是报告的四层之首：在定量层之前先回答
「这是给谁看的什么类型的连载、读者每章最低得到什么」。与第二/三部分同构，
LLM 只输出标题行，正文由 JSON 机器块的 ``writer_contract`` 渲染——
单一真源契约对四层一体适用。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Tuple

# 显式缺省通道：语料证据不足以合成某字段时允许声明缺失，禁止编造。
NOT_PROVIDED = "报告未提供"

FIELDS = ["positioning", "purpose", "style_marks_synthesis"]

MIN_FIELD_CHARS = 5
MIN_ENEMY_CLAUSES = 2
MAX_ENEMY_CLAUSES = 4


@dataclass
class WriterContract:
    positioning: str
    purpose: str
    style_marks_synthesis: str
    enemy_clauses: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "positioning": self.positioning,
            "purpose": self.purpose,
            "style_marks_synthesis": self.style_marks_synthesis,
            "enemy_clauses": list(self.enemy_clauses),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WriterContract":
        data = data if isinstance(data, dict) else {}
        clauses_raw = data.get("enemy_clauses", [])
        clauses = []
        if isinstance(clauses_raw, list):
            clauses = [str(c).strip() for c in clauses_raw if str(c).strip()]
        elif isinstance(clauses_raw, str) and clauses_raw.strip():
            # 容忍 LLM 把多条写成一个字符串：按换行/分号拆分
            clauses = [
                part.strip()
                for part in clauses_raw.replace("；", "\n").replace(";", "\n").splitlines()
                if part.strip()
            ]
        return cls(
            positioning=str(data.get("positioning", "")).strip(),
            purpose=str(data.get("purpose", "")).strip(),
            style_marks_synthesis=str(data.get("style_marks_synthesis", "")).strip(),
            enemy_clauses=clauses,
        )

    def validate(self) -> Tuple[bool, List[str]]:
        """三个文本字段非空（≥5 字）或显式「报告未提供」；敌人条款 2–4 条。"""
        errors: List[str] = []
        for field in FIELDS:
            value = str(getattr(self, field, "")).strip()
            if not value:
                errors.append(f"WriterContract: field '{field}' 不能为空（或显式写「{NOT_PROVIDED}」）")
            elif len(value) < MIN_FIELD_CHARS and value != NOT_PROVIDED:
                errors.append(f"WriterContract: field '{field}' 过短（{len(value)} < {MIN_FIELD_CHARS} 字）")
        if not self.enemy_clauses:
            errors.append("WriterContract: enemy_clauses 不能为空（2–4 条，或逐条写「报告未提供」）")
        elif not (MIN_ENEMY_CLAUSES <= len(self.enemy_clauses) <= MAX_ENEMY_CLAUSES):
            errors.append(
                f"WriterContract: enemy_clauses 需 {MIN_ENEMY_CLAUSES}–{MAX_ENEMY_CLAUSES} 条，实际 {len(self.enemy_clauses)} 条"
            )
        return (len(errors) == 0, errors)

    def render_markdown(self) -> str:
        clauses = "\n".join(f"- {c}" for c in self.enemy_clauses) or f"- {NOT_PROVIDED}"
        lines = [
            "### 〇.1 定位（Positioning）",
            f"{self.positioning}\n",
            "### 〇.2 写作目的与读者契约（Purpose & Reader Contract）",
            f"{self.purpose}\n",
            "### 〇.3 风格标记综合（Style Marks Synthesis）",
            f"{self.style_marks_synthesis}\n",
            "### 〇.4 敌人条款（Enemy Clauses）",
            clauses,
        ]
        return "\n".join(lines)
