# -*- coding: utf-8 -*-
"""三套可复用风格模板：识别 / 转写 / 对话生成。

归档版 v7.0.0 在 `prompt_templates.py` 里提供 `STYLE_TEMPLATES`（identification
/ transfer / dialogue_generation），全部以 `{author_name}` 与定量约束渲染。这里
恢复三套模板，但**数值一律取自 report.json 的实测值**（`_band`/`_limit` 同源自
`persona.system_prompt`），并且默认走脱敏原型口径：模板里不出现真实作者名，改用
风格载体描述。这样模板既能被复用，又不会成为身份泄漏的新通道。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .._numbers import trim_decimal

_MISSING = "本次未测得"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return _MISSING
    return trim_decimal(value, digits)


def _pct(value: Any) -> str:
    return str(value) if value not in (None, "") else _MISSING


def _band(value: Optional[float], low: float, high: float, unit: str = "字", digits: int = 0) -> str:
    if value is None:
        return _MISSING
    return f"{value * low:.{digits}f}-{value * high:.{digits}f}{unit}"


def _style_kernel(report_json: Dict[str, Any]) -> str:
    """A name-free style descriptor, safe for public templates."""
    quant = report_json.get("quantitative_features", {}) or {}
    markers = quant.get("style_markers", []) or []
    if markers:
        return "、".join(str(m) for m in markers[:2])
    return "稳健叙事与机制化想象"


def _quant_table(report_json: Dict[str, Any]) -> str:
    """The measured fingerprint shared by all three templates."""
    q = report_json.get("quantitative_features", {}) or {}
    sent = q.get("sentence_structure", {}) or {}
    para = q.get("paragraph_rhythm", {}) or {}
    dlg = q.get("dialogue_features", {}) or {}
    punc = q.get("punctuation_density", {}) or {}
    rh = q.get("rhetoric_features", {}) or {}
    rows = [
        ("平均句长", f"{_fmt(_num(sent.get('avg_sent_len')))} 字"),
        ("短句率（≤10字）", _pct(sent.get("short_sent_ratio_pct"))),
        ("长句率（≥50字）", _pct(sent.get("long_sent_ratio_pct"))),
        ("平均段长", f"{_fmt(_num(para.get('avg_para_len')))} 字"),
        ("极短段率（≤8字）", _pct(para.get("short_para_ratio_pct"))),
        ("对话占比", _pct(dlg.get("dialogue_ratio_pct"))),
        ("道:说 配比", _fmt(_num(dlg.get("dao_shuo_ratio")), 2)),
        ("逗号密度", f"{_fmt(_num(punc.get('comma')), 2)}/千字"),
        ("感叹号密度", f"{_fmt(_num(punc.get('exclamation')), 2)}/千字"),
        ("省略号密度", f"{_fmt(_num(punc.get('ellipsis')), 2)}/千字"),
        ("破折号密度", f"{_fmt(_num(punc.get('dash')), 2)}/千字"),
        ("比喻密度", f"{_fmt(_num(rh.get('metaphor_density')), 2)}/千字"),
    ]
    return "\n".join(f"| {name} | {value} |" for name, value in rows)


def render_identification(report_json: Dict[str, Any]) -> str:
    """Template 1 — style identification with a 5-dimension 1–10 score."""
    kernel = _style_kernel(report_json)
    return f"""你是一位专业的文学风格识别专家。请根据以下定量特征，判断输入文本是否符合
「{kernel}」这一风格内核。

## 待识别文本的定量特征

（由调用方填入待识别文本的实测特征；下方为风格基准）

| 指标 | 实测基准 |
|---|---|
{_quant_table(report_json)}

## 识别任务

从以下五个维度逐项判断匹配度，**每项必须给出数值理由**（写明目标值与待识别值的差）：

1. **句式节奏匹配度**：平均句长、短句率、长句率是否落在目标区间
2. **词汇特征匹配度**：用词密度、高频功能词分布是否一致
3. **段落结构匹配度**：平均段长、极短段率是否一致
4. **标点使用匹配度**：逗号/感叹号/省略号/破折号的密度分布是否一致
5. **对话模式匹配度**：对话占比、对话标签使用习惯是否一致

## 输出要求

- 综合匹配度评分（1–10）
- 各维度评分 + 数值对照理由
- 最符合与最不符合风格特征的片段引用（引用时用中性指涉，不出现原作专名）
- **综合匹配度 < 6 分时，必须给出至少 3 条具体修改建议**（指明改哪一项、改到什么量级）
"""


def render_transfer(report_json: Dict[str, Any]) -> str:
    """Template 2 — rewrite an input text into the measured style."""
    q = report_json.get("quantitative_features", {}) or {}
    sent = q.get("sentence_structure", {}) or {}
    para = q.get("paragraph_rhythm", {}) or {}
    dlg = q.get("dialogue_features", {}) or {}
    punc = q.get("punctuation_density", {}) or {}
    rh = q.get("rhetoric_features", {}) or {}

    avg_sent = _num(sent.get("avg_sent_len"))
    avg_para = _num(para.get("avg_para_len"))
    short_pct = _pct(sent.get("short_sent_ratio_pct"))

    cards = report_json.get("technique_cards", []) or []
    card_lines = "\n".join(
        f"- [{c.get('id', 'T??')}] {c.get('name', '技法')}：{c.get('definition', '')}"
        for c in cards
    ) or "- （无技法卡数据）"
    voiceprint = report_json.get("voiceprint", {}) or {}
    voice_lines = "\n".join(
        f"- {label}：口吻 {vp.get('tone_type', '—')}；口头禅 {('、'.join(vp.get('catchphrases') or []) or '—')}"
        for label, vp in voiceprint.items() if isinstance(vp, dict)
    ) or "- （无实测话术数据）"

    return f"""你是一位精通「{_style_kernel(report_json)}」风格的文学转写专家。
请将下方输入文本改写成该风格。

## 目标风格约束（必须遵守）

### 硬性统计指标（取自本次实测）
- 平均句长：{_band(avg_sent, 0.85, 1.15, "字", 0)}
- 短句率（≤10字）：{short_pct}
- 平均段长：{_band(avg_para, 0.85, 1.15, "字", 0)}
- 对话占比：{_pct(dlg.get("dialogue_ratio_pct"))}
- 逗号密度 {_fmt(_num(punc.get('comma')), 2)}/千字 · 感叹号 {_fmt(_num(punc.get('exclamation')), 2)}/千字 · 省略号 {_fmt(_num(punc.get('ellipsis')), 2)}/千字 · 破折号 {_fmt(_num(punc.get('dash')), 2)}/千字
- 比喻密度：{_fmt(_num(rh.get('metaphor_density')), 2)}/千字

### 可调用技法（按需选用，不必全用）
{card_lines}

### 原型口吻（对话部分必须贴合）
{voice_lines}

## 转写规则（六条，逐条适用）

1. 保留原文核心情节与信息，不增删事实
2. 句式调整到目标平均句长与短句率区间内
3. 词汇替换为与该风格高频词一致的表达，删除书面连接词堆砌
4. 段落切分对齐目标平均段长与极短段率
5. 标点使用模式对齐实测密度分布
6. 叙事节奏紧凑：**每 300 字内至少出现 1 次对话或动作**

## 输入文本

（由调用方填入）

## 输出要求

输出转写后的文本，末尾附实测对照数据（任一项不达标即视为不合格）：
- 转写后平均句长（目标：{_band(avg_sent, 0.85, 1.15, "字", 0)}）
- 转写后短句率（目标：{short_pct}）
- 转写后极短段率（目标：{_pct(para.get('short_para_ratio_pct'))}）
"""


def render_dialogue_generation(report_json: Dict[str, Any]) -> str:
    """Template 3 — generate character dialogue from measured voices."""
    q = report_json.get("quantitative_features", {}) or {}
    sent = q.get("sentence_structure", {}) or {}
    dlg = q.get("dialogue_features", {}) or {}
    voiceprint = report_json.get("voiceprint", {}) or {}

    voice_lines = "\n".join(
        f"- **{label}**：口吻类型 {vp.get('tone_type', '—')}；平均台词 {vp.get('avg_speech_len', '—')} 字；"
        f"常用标签 {('、'.join(vp.get('common_tags') or []) or '—')}；"
        f"口头禅 {('、'.join(vp.get('catchphrases') or []) or '—')}；"
        f"常见起句 {('、'.join(vp.get('opening_words') or []) or '—')}"
        for label, vp in voiceprint.items() if isinstance(vp, dict)
    ) or "- （未取得实测话术数据：按对话规范执行，保持角色间可辨识差异）"

    return f"""你是一位风格载体型作家笔下的角色对话生成器。请严格按以下设定生成角色对话。

## 角色设定（实测话术，原型标签）

{voice_lines}

## 对话风格约束（必须遵守）

- 全篇对话占比约 {_pct(dlg.get("dialogue_ratio_pct"))}
- 道:说 配比约 {_fmt(_num(dlg.get('dao_shuo_ratio')), 2)}:1（标签不得等量化使用）
- 平均句长 {_band(_num(sent.get('avg_sent_len')), 0.85, 1.15, "字", 0)}；对话句可比叙述句更短

## 场景

（由调用方填入）

## 生成规则（六条）

1. 每句对话必须符合其角色的实测口吻（tone_type / 口头禅 / 起句习惯）
2. 单轮台词长度贴合该角色实测平均台词长度，超长必须切成多轮
3. 必须使用该角色的标志性语言特征（口头禅、常用标签）
4. 对话必须推动剧情或揭示关系，禁止无信息量的水对话
5. 禁止说教与直白的情绪宣告（「我很生气」这类写法）
6. 每段对话之间穿插至少 1 句动作或环境描写，避免纯对话墙
"""


_TEMPLATES = {
    "identification": render_identification,
    "transfer": render_transfer,
    "dialogue_generation": render_dialogue_generation,
}

STYLE_TEMPLATE_NAMES = tuple(_TEMPLATES)


def render_all_style_templates(report_json: Dict[str, Any]) -> Dict[str, str]:
    """Render every template — used to populate report.json's ``style_templates``."""
    return {name: fn(report_json) for name, fn in _TEMPLATES.items()}
