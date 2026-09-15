# -*- coding: utf-8 -*-
"""场景强化指令（六场景）——生成侧指导，可选注入分身提示词。

归档版 v7.0.0 的 `SCENE_TEMPLATES` 是一组硬编码阈值（「短句必须占 70% 以上」
「环境描写不超过 3 句」）。直接照搬会与本技能的第一防线冲突：分身提示词里的
每条量化约束都必须能回溯到本次实测值（指标+数值+单位）。

所以这里做**参数化**：把固定阈值改写成对实测基线的相对指令——「不超过平均句长
×1.5」，其中平均句长取自本次语料的真实测量。它属于**生成侧指令**，与
`system_prompt._DEMO_CORRECT` 同类：不受「报告正文数值只能来自占位符」约束
（那约束管的是分析报告，不是给模型的写作指导），但必须显式标注为生成指导。

缺省（`scene_type=None`）时不注入任何内容，完全保持既有行为。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .._numbers import trim_decimal

SCENE_TYPES = ("battle", "dialogue", "scene", "emotion", "momentum", "transition")

SCENE_LABELS: Dict[str, str] = {
    "battle": "战斗场景",
    "dialogue": "对话场景",
    "scene": "场景描写",
    "emotion": "情感场景",
    "momentum": "气势场景",
    "transition": "转场场景",
}

_MISSING = "本次未测得该基线"


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _fmt(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return _MISSING
    return trim_decimal(value, digits)


def build_scene_enhancement(
    scene_type: str,
    quant: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the enhancement block for one scene type.

    Every numeric reference is expressed relative to a measured baseline
    (``平均句长``, ``平均段长``) so the instruction stays faithful to the current
    corpus instead of the archive's frozen constants.
    """
    quant = quant or {}
    sent = quant.get("sentence_structure", {}) or {}
    para = quant.get("paragraph_rhythm", {}) or {}
    dlg = quant.get("dialogue_features", {}) or {}
    punc = quant.get("punctuation_density", {}) or {}

    avg_sent = _num(sent.get("avg_sent_len"))
    avg_para = _num(para.get("avg_para_len"))
    short_ratio = sent.get("short_sent_ratio_pct") or _MISSING
    exclaim = _num(punc.get("exclamation"))
    dialogue_ratio = dlg.get("dialogue_ratio_pct") or _MISSING

    label = SCENE_LABELS.get(scene_type, scene_type)
    sent_cap = f"{_fmt(avg_sent * 1.5, 0)} 字" if avg_sent is not None else _MISSING
    slow_cap = f"{_fmt(avg_sent + 5, 0)} 字" if avg_sent is not None else _MISSING
    hard_cap = f"{_fmt(avg_sent * 1.2, 0)} 字" if avg_sent is not None else _MISSING
    para_hint = f"{_fmt(avg_para * 0.6, 0)} 字" if avg_para is not None else _MISSING

    rules: Dict[str, list] = {
        "battle": [
            f"短句（≤10 字）占比抬升至高于全篇实测 {short_ratio} 的水位，形成冲刺节拍",
            "每句至少承载一个可拍成画面的动作，动词密度显著高于叙述段",
            f"单句硬上限 {hard_cap}，超限即断句",
            "纯心理描写压缩到零，情绪一律通过动作与身体反应外化",
            f"感叹号可启用，但密度仍须低于铁律 4 的实测上限（{_fmt(exclaim, 2)}/千字 量级）",
        ],
        "dialogue": [
            f"对话占段落的主体，叙述只承担衔接（全篇实测对话占比 {dialogue_ratio}）",
            "每句引语必须符合对应原型的实测口吻（见「角色声音参考」）",
            "省略号仅限迟疑，每千字至多一次，不得拖尾成习惯",
            "口语化功能词的比例高于叙述段，书面连接词退场",
            "对话须推动信息或关系，禁止无目的寒暄",
        ],
        "scene": [
            "环境描写不超过 3 句，且必须经角色感官呈现（视角在角色身上）",
            "优先视觉与听觉，嗅觉与触觉为辅",
            f"允许中长句铺陈，但单句不超过平均句长×1.5（{sent_cap}）",
            "环境信息必须服务情节或情绪，禁止为写景而写景",
        ],
        "emotion": [
            "心理描写不超过 2 句，其余用行为替代情绪宣泄",
            "优先意象化表达（用攥紧的拳头替代「他很愤怒」）",
            f"节奏可放缓，但单句不超过平均句长+5 字（{slow_cap}）",
            "禁止直写「他感到很X」，情绪必须由动作或对话暗示",
        ],
        "momentum": [
            "排比至少一组（三句以上），形成压迫感",
            f"单句不超过 {hard_cap}，句句收紧",
            "每句必含动作，动词密度与战斗段同级",
            "禁止犹豫、停顿与自我怀疑的描写",
        ],
        "transition": [
            "过渡必须由角色动作完成（走/看/说），禁止用「与此同时」类旁白黏合",
            f"转场段控制在 {para_hint} 字上下（全篇实测平均段长 {_fmt(avg_para, 0)} 字）",
            "新场景首句必须是对话或动作，禁止环境切入",
            "前后节奏保持一致，禁止突然放缓",
        ],
    }

    if scene_type not in SCENE_TYPES:
        return ""
    body = "\n".join(f"- {rule}" for rule in rules[scene_type])
    return (
        f"\n## 场景强化指令：{label}（生成指导）\n\n"
        "> 以下是写作时的场景化操作指导，其中的数值都是相对**本次实测基线**的"
        "相对约束（括号内绝对值取自本语料测量），不覆盖铁律 1–6 与量化禁令。\n\n"
        f"{body}\n"
    )


def add_scene_enhancement(
    prompt: str,
    scene_type: Optional[str],
    quant: Optional[Dict[str, Any]] = None,
) -> str:
    """Append a scene block to a persona prompt; no-op when unset/invalid."""
    if not scene_type or scene_type not in SCENE_TYPES:
        return prompt
    block = build_scene_enhancement(scene_type, quant)
    return prompt + block if block else prompt
