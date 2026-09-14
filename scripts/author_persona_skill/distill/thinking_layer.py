# -*- coding: utf-8 -*-
"""Thinking Layer definitions, schema validation, and rendering."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class ThinkingLayer:
    attention_order: str
    info_control: str
    conflict_escalation: str
    cost_management: str
    closure: str
    long_arc: str
    adaptation_boundary: str

    REQUIRED_KEYS = [
        "attention_order",
        "info_control",
        "conflict_escalation",
        "cost_management",
        "closure",
        "long_arc",
        "adaptation_boundary",
    ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attention_order": self.attention_order,
            "info_control": self.info_control,
            "conflict_escalation": self.conflict_escalation,
            "cost_management": self.cost_management,
            "closure": self.closure,
            "long_arc": self.long_arc,
            "adaptation_boundary": self.adaptation_boundary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThinkingLayer":
        return cls(
            attention_order=str(data.get("attention_order", "")).strip(),
            info_control=str(data.get("info_control", "")).strip(),
            conflict_escalation=str(data.get("conflict_escalation", "")).strip(),
            cost_management=str(data.get("cost_management", "")).strip(),
            closure=str(data.get("closure", "")).strip(),
            long_arc=str(data.get("long_arc", "")).strip(),
            adaptation_boundary=str(data.get("adaptation_boundary", "")).strip(),
        )

    def validate(self) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        for key in self.REQUIRED_KEYS:
            val = getattr(self, key, "").strip()
            if not val:
                errors.append(f"ThinkingLayer: field '{key}' cannot be empty")
            elif len(val) < 5:
                errors.append(f"ThinkingLayer: field '{key}' is too short (min 5 chars)")
        return (len(errors) == 0, errors)

    def render_markdown(self) -> str:
        lines = [
            "### 3.1 注意力顺序 (Attention Order)",
            f"{self.attention_order}\n",
            "### 3.2 信息控制 (Info Control)",
            f"{self.info_control}\n",
            "### 3.3 冲突升级 (Conflict Escalation)",
            f"{self.conflict_escalation}\n",
            "### 3.4 代价管理 (Cost Management)",
            f"{self.cost_management}\n",
            "### 3.5 收束方式 (Closure Pattern)",
            f"{self.closure}\n",
            "### 3.6 长线布局 (Long Arc)",
            f"{self.long_arc}\n",
            "### 3.7 题材适配边界 (Adaptation Boundary)",
            f"{self.adaptation_boundary}",
        ]
        return "\n".join(lines)
