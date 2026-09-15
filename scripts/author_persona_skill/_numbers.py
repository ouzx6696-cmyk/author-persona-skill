# -*- coding: utf-8 -*-
"""数值展示的单一实现。

四个产物模块（report.renderer、persona.style_templates / scene_templates /
system_prompt）此前各自复制了同一段 ``f"{v:.{d}f}".rstrip("0")``。该写法在
``digits=0`` 时会把整十数截断——``100`` → ``"1"``、``2400`` → ``"24"``——
而整数指标（如 hapax 计数）直接进公开产物，属数值保真缺陷。收敛到此处：
**只有小数点之后**才允许去尾零。
"""
from __future__ import annotations


def trim_decimal(value: float, digits: int = 2) -> str:
    """定宽小数字符串，去掉小数点后的冗余零，但绝不碰整数位。"""
    out = f"{value:.{digits}f}"
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out
