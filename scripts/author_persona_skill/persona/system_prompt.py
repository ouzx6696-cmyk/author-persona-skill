# -*- coding: utf-8 -*-
"""System prompt builder for optional standalone LLM personas.

Reference-grade output: numeric iron rules derived from measured metrics,
synthetic correct/incorrect demonstrations, and forbidden-action lists.
No original corpus text is ever embedded — demos use invented characters.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .._numbers import trim_decimal
from ..analyzers.knowledge import GENERIC_TABOO_PHRASES

_MISSING = "未知（数据缺失）"


def _assert_quantified_bans(lines: List[str]) -> None:
    """量化禁令必须携带实测数值（指标+数值+单位）；缺值在生成期即失败。

    An ellipsis/dash ban must carry its measured value, not just a usage note;
    otherwise the persona would silently lose the number and violate the
    metric+value+unit triple. This check surfaces such defects at generation
    time instead of leaking them into the persona prompt.
    """
    in_bans = False
    for line in lines:
        if "## 量化禁令" in line:
            in_bans = True
            continue
        if in_bans and "## 对话规范" in line:
            break
        if in_bans and line.startswith("- ") and "未知" not in line and not re.search(r"\d", line):
            raise ValueError(f"量化禁令缺少实测数值（指标+数值+单位）: {line}")


def _pct(value: Any) -> str:
    """Render a measured percentage or an explicit missing marker.

    Missing data renders as an explicit placeholder, never as a fabricated
    "measured" number.
    """
    return str(value) if value not in (None, "") else _MISSING


def _num(value: Any) -> Optional[float]:
    """Coerce to float; None (not a fabricated default) means data missing."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num_out(value: Optional[float], digits: int = 1) -> str:
    """Render a measured number or an explicit missing marker."""
    if value is None:
        return _MISSING
    return trim_decimal(value, digits)


def _band(
    value: Optional[float],
    low_factor: float,
    high_factor: float,
    unit: str = "字",
    digits: int = 0,
) -> str:
    """Render a tolerance band around a measured baseline."""
    if value is None:
        return _MISSING
    return f"{value * low_factor:.{digits}f}-{value * high_factor:.{digits}f}{unit}"


def _derive_tag_rules(dialogue_features: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Return (main-rule text, forbidden decorative tags)."""
    freqs: Dict[str, int] = dialogue_features.get("tag_frequencies", {})
    ranked = sorted(freqs.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return ("以「道」为绝对主力对话标签，辅以「说」「问」", ["低声道", "沉声道", "冷笑道", "娇笑道"])
    top = [t for t, _ in ranked[:3]]
    main_rule = f"对话标签只用 {'、'.join('「' + t + '」' for t in top)} 三类（实测占比依次为 {', '.join(f'{t}{c}次' for t, c in ranked[:3])}）"
    decorative_pool = ["低声道", "沉声道", "轻声道", "柔声道", "冷笑道", "娇笑道", "嗔道", "喜道", "怒道", "叹道", "喃喃道"]
    forbidden = [t for t in decorative_pool if t not in freqs or freqs.get(t, 0) < max(1, ranked[0][1] // 20)]
    return main_rule, forbidden[:6]


# Synthetic demo characters — deliberately generic so no corpus text is needed.
_DEMO_CORRECT = """林澈把图纸铺在桌上，指尖压住卷起的边角。
苏芜端着灯凑过来，火光晃了晃。
「这条线，为什么绕开河道？」她问。
「汛期水位会涨。」林澈说。
「那桥墩——」
「改到高地上去。明天量地。」"""

_DEMO_INCORRECT = """林澈深邃的眼眸中闪过一丝复杂的神色，他幽幽地叹息着，缓缓开口道：「唉……也许，这就是命运吧……」（错误：修饰性标签堆叠、省略号滥用、感叹式自语、无信息量的抒情——全部违反铁律）"""


def build_system_prompt(
    report_json: Dict[str, Any],
    allow_author_identity: bool = False,
) -> str:
    """
    Build structured system prompt from report JSON.

    Numeric rules are derived from measured quantitative features with explicit
    tolerance bands; macro thinking comes from the thinking layer; demonstrations
    are synthetic. Supports desensitized archetype mode (default) and signed mode.
    """
    meta = report_json.get("meta", {})
    work_title = meta.get("work_title", "作品")
    author_name = meta.get("author_name", "佚名")

    quant = report_json.get("quantitative_features", {})
    sent = quant.get("sentence_structure", {})
    para = quant.get("paragraph_rhythm", {})
    dlg = quant.get("dialogue_features", {})
    punc = quant.get("punctuation_density", {})
    rh = quant.get("rhetoric_features", {})
    desc = quant.get("description_density", {})

    cards = report_json.get("technique_cards", [])
    thinking = report_json.get("thinking_layer", {})

    avg_sent = _num(sent.get("avg_sent_len"))
    short_pct = _pct(sent.get("short_sent_ratio_pct"))
    long_pct = _pct(sent.get("long_sent_ratio_pct"))
    avg_para = _num(para.get("avg_para_len"))
    a_m_ratio = _num(desc.get("action_mental_ratio"))
    exl = _num(punc.get("exclamation"))
    qst = _num(punc.get("question"))
    ell = _num(punc.get("ellipsis"))
    dash = _num(punc.get("dash"))
    colon = _num(punc.get("colon"))
    comma = _num(punc.get("comma"))
    period = _num(punc.get("period"))
    cp_ratio = _num(quant.get("punctuation_ratios", {}).get("comma_period_ratio"))
    met = _num(rh.get("metaphor_density"))
    par = _num(rh.get("parallelism_density"))
    dao_shuo = _num(dlg.get("dao_shuo_ratio"))

    def _bl(value: Optional[float], unit: str = "字") -> str:
        """Append '（实测基线 X 字）' or an explicit missing note."""
        if value is None:
            return "（无实测基线）"
        return f"（实测基线 {_num_out(value, 1)}{unit}）"

    def _limit(value: Optional[float], factor: float, unit: str = "/千字", digits: int = 1) -> str:
        """Render '≤X/千字' or an explicit missing marker (never a fabricated 0)."""
        if value is None:
            return _MISSING
        return f"≤{value * factor:.{digits}f}{unit}"

    lines: List[str] = []

    # 0. Identity
    lines.append("# 作家分身系统提示词")
    if allow_author_identity:
        lines.append(f"\n## 角色定义\n\n你是深度模仿【{author_name}】写作风格的作家分身，用于创作全新的、独立的故事；你不是在续写其任何具体作品。")
    else:
        style_markers = quant.get("style_markers", [])
        kernel = "、".join(style_markers[:2]) if style_markers else "稳健叙事与机制化想象"
        lines.append(f"\n## 角色定义\n\n你是一位风格载体型作家分身，内核特征为「{kernel}」。你模仿的是一种写作风格，不对应任何真实作者或具体作品。")

    # 1. Iron rules (numeric, from measurements)
    tag_rule, tag_forbidden = _derive_tag_rules(dlg)
    # 主力对话标签（如"道"）：用于给 道:说 配比提供主语。
    _tag_freqs: Dict[str, Any] = dlg.get("tag_frequencies", {}) or {}
    _top_tag = (
        max(_tag_freqs, key=lambda k: _tag_freqs[k])
        if isinstance(_tag_freqs, dict) and _tag_freqs else ""
    )
    lines.append("\n## 核心风格DNA（数值铁律）\n")

    # 道:说 比例是极强的风格指纹（本语料 3.79），只列标签种类而不给比例会让
    # 分身把各标签等量化用（实测试写道说比 3.79 -> 1.00，偏离 -73.6%）。
    ratio_line = (
        f"- **配比**：主力标签「{_top_tag or '道'}」与其余标签的实测用量比约 {_num_out(dao_shuo, 2)}:1，"
        f"写作时须复现该倾斜，不得把各类标签等量化使用"
        if dao_shuo and _top_tag else ""
    )
    lines.append(f"""### 铁律1：{tag_rule.split("（")[0]}
- **规则**：{tag_rule}{chr(10) + ratio_line if ratio_line else ""}
- **禁止**使用以下修饰性标签：{'、'.join(tag_forbidden)}
- **原因**：情绪由引语内容承载，标签只负责归属说话人""")

    # 长句既要"不超过上限"也要"保留一定比例"：只给上会让分身通篇堆短句
    # （实测试写长句率 7.6% -> 0%，连带句号密度 +109%）。
    keep_long = (
        f"- 长句（≥50字）占比维持 {long_pct} 左右（实测基线），**必须保留少量长句做铺陈与信息压缩**，不得通篇短句"
        if long_pct and str(long_pct) != _MISSING else ""
    )
    lines.append(f"""
### 铁律2：句式节奏
- 平均句长控制在 {_band(avg_sent, 0.85, 1.15, "字", 0)} {_bl(avg_sent)}
- 短句（≤10字）占比不低于 {short_pct} 的八成{chr(10) + keep_long if keep_long else ""}
- 长短句交替：以中短句推进，用少量长句承载密集信息，避免全篇同一节奏""")

    lines.append(f"""
### 铁律3：段落结构
- 平均段落长度 {_band(avg_para, 0.85, 1.15, "字", 0)} {_bl(avg_para)}
- 极短段（≤8字）仅用于重锤瞬间（占比 {_pct(para.get('short_para_ratio_pct'))})
- 对话与动作可在同段衔接：引语可用逗号收尾接续动作，再开启下一句引语""")

    # A punctuation is "active" when its measured density has real presence.
    # The old hard-coded absolute threshold (>=1.5) wrongly zeroed e.g. an
    # ellipsis measured at 1.13/千字 that the report itself diagnosed as the
    # style's only emotional relief valve. Presence is judged by whether the
    # measured value clears a low "meaningful existence" floor (0.5/千字);
    # below that it is treated as effectively absent and banned. This keeps
    # the ban direction aligned with the measured data: active marks get a
    # measured allowance, near-zero marks get a measured ban.
    #
    # Every punctuation the analyzer measured must get a rule. Earlier only
    # three marks were emitted, so question/comma/period/colon drifted freely
    # in generated prose (measured: question 3.14 -> 0, colon 2.94 -> 9.80).
    _ACTIVE_FLOOR = 0.5

    def _punctuation_rule(name: str, value: Optional[float], allow_note: str, ban_note: str) -> str:
        """One punctuation rule whose wording follows the measured data.

        Active marks get an allowance carrying BOTH the measured cap and an
        explicit measured baseline (so the 指标+数值+单位 triple stays
        traceable). Near-zero marks get a ban carrying the true measured value.
        Used by both the iron rules and the quantified-ban list so the two
        sections can never contradict each other -- they once did (a hard-coded
        "感叹号低频" ban against a measured 8.99/千字), which made the persona
        suppress the very feature it was supposed to reproduce.
        """
        if value is None:
            return f"- {name}：{_MISSING}，按禁用处理（无实测数据）"
        if value > _ACTIVE_FLOOR:
            return (f"- {name}：{_limit(value, 1.3)}（实测基线 {_num_out(value, 2)}/千字），"
                    f"{allow_note}")
        return f"- {name}：{_num_out(value, 2)}/千字，实测近零，{ban_note}"

    punctuation_lines = [
        "### 铁律4：标点纪律",
        _punctuation_rule("感叹号", exl, "允许情绪爆发、命令与高强语气，密度维持在此量级", "情绪不外放（靠内容与停顿表达，不用标点爆发情绪）"),
        _punctuation_rule("问号", qst, "允许质疑、反问与探询，密度维持在此量级", "少用疑问句（语气以陈述与判断为主）"),
        _punctuation_rule("省略号", ell, "允许对白迟疑与场景分隔，禁用无意义拖尾", "按禁用处理"),
        _punctuation_rule("破折号", dash, "允许自我修正或补注，禁用成对插入语滥用", "按禁用处理"),
        _punctuation_rule("冒号", colon, "允许引出说明、列举与引语", "少用冒号（改用逗号或独立短句承接）"),
    ]
    # 结构类标点（逗号/句号）不是"用不用"的问题，而是"多密"的问题：
    # 给密度区间 + 逗句比，避免试写文本逗句比失控（实测曾 2.96 -> 1.96）。
    punctuation_lines.append(
        f"- 逗号 {_band(comma, 0.85, 1.15, '/千字', 1)}（实测基线 {_num_out(comma, 2)}/千字），"
        f"句号 {_band(period, 0.85, 1.15, '/千字', 1)}（实测基线 {_num_out(period, 2)}/千字）"
    )
    punctuation_lines.append(
        f"- 逗句比（逗号÷句号）维持 {_band(cp_ratio, 0.85, 1.15, ':1', 2)}"
        f"（实测基线 {_num_out(cp_ratio, 2)}:1），逗号管推进、句号管收束，二者比例不得倒置"
    )
    lines.append("\n" + "\n".join(punctuation_lines))

    # 只给"动作:心理"比值不够——"禁止连续3段心理独白"会被理解成"尽量别写心理"
    # （实测试写 4.53 -> 10.0，+120%）。补一句：心理不是可省项，须按比例出现。
    lines.append(f"""
### 铁律5：描写双轨配比
- 动作主导句 : 心理主导句 ≈ {_num_out(a_m_ratio, 1)}:1（允许 ±20% 浮动）
- **心理句是必写项而非可省项**：每 {max(2, round(a_m_ratio or 4))} 句动作句后应有约 1 句心理/内部反应句，
  "禁止连续 3 段纯心理独白"是限制集中堆放，不是允许删空心理描写
- 心理描写必须紧贴动作之后，形成"外部行动→内部反应"节拍链
- 环境描写经由角色感知带出，不做全知全景""")

    par_line = (
        f"- 排比密度维持 {_band(par, 0.7, 1.3, '/千字', 2)}（实测基线 {_num_out(par, 2)}/千字），"
        f"排比只用于气势收束，禁止通篇排句"
        if par is not None else ""
    )
    lines.append(f"""
### 铁律6：比喻策略
- 比喻句密度维持 {_band(met, 0.7, 1.3, "/千字", 1)} {_bl(met, "/千字")}
- 映射源必须是日常可感的具体经验，服务于"把陌生转译为熟悉"
- 禁止华丽辞藻式比喻与排比堆叠{chr(10) + par_line if par_line else ""}""")

    # 1.5 Quantified bans: every ban is an executable metric+value+unit triple,
    #     worded by the same helper as the iron rules so the two never diverge.
    lines.append("\n## 量化禁令（指标+数值+单位）\n")
    lines.extend([
        f"- 平均句长：{_band(avg_sent, 0.85, 1.15, '字', 0)} {_bl(avg_sent)}",
        f"- 长句（≥50字）占比：维持 {long_pct}" if long_pct and str(long_pct) != _MISSING else "",
        _punctuation_rule("感叹号", exl, "允许情绪爆发与命令，密度维持在此量级", "情绪高潮也不用感叹号"),
        _punctuation_rule("问号", qst, "允许质疑与反问，密度维持在此量级", "少用疑问句"),
        _punctuation_rule("省略号", ell, "仅限对白迟疑与场景分隔", "对白迟疑与场景分隔之外禁用"),
        _punctuation_rule("破折号", dash, "仅限自我修正与补注", "自我修正与补注之外禁用"),
        _punctuation_rule("冒号", colon, "允许引出说明与列举", "少用冒号"),
        f"- 逗句比：维持 {_num_out(cp_ratio, 2)}:1（实测基线），逗号管推进、句号管收束",
        f"- 道:说 配比：约 {_num_out(dao_shuo, 2)}:1" if dao_shuo else "",
        f"- 动作主导句 : 心理主导句 ≈ {_num_out(a_m_ratio, 1)}:1（±20% 浮动；心理句为必写项）",
        "- 心理独白：连续不得超过 3 段",
        f"- 比喻密度：{_band(met, 0.7, 1.3, '/千字', 1)} {_bl(met, '/千字')}",
        f"- 排比密度：{_band(par, 0.7, 1.3, '/千字', 2)}（实测基线 {_num_out(par, 2)}/千字）" if par is not None else "",
        f"- 极短段（≤8字）：仅用于重锤瞬间，占比不超过 {_pct(para.get('short_para_ratio_pct'))}",
    ])
    # 描写配比与连续句禁令：归档版 build_customized_taboos 的极端值禁令，迭代中丢失。
    # 每条都按实测占比决定方向（过少→上限，过多→下限），数值直接写进禁令文本，
    # 从而满足 _assert_quantified_bans 的「指标+数值+单位」要求。
    _desc_total = sum(
        v for v in (_num(desc.get("action_count")), _num(desc.get("mental_count")),
                    _num(desc.get("env_count"))) if v is not None)
    _env_pct = (_num(desc.get("env_count")) / _desc_total * 100.0) if _desc_total else None
    _psych_pct = (_num(desc.get("mental_count")) / _desc_total * 100.0) if _desc_total else None
    _short_rate = _num(sent.get("short_sent_ratio"))
    if _short_rate is None and sent.get("short_sent_ratio_pct") not in (None, ""):
        _short_rate = _num(str(sent.get("short_sent_ratio_pct")).rstrip("%"))
    if _short_rate is not None and _short_rate <= 1.0:
        _short_rate *= 100.0
    _dlg_ratio = _num(dlg.get("dialogue_ratio"))
    _dialogue_driven = _dlg_ratio is not None and _dlg_ratio > 0.5

    if _env_pct is not None:
        if _env_pct < 10:
            lines.append(f"- 环境描写：实测占比仅 {_env_pct:.1f}%，单次环境描写不超过 2 句，氛围靠角色感知呈现")
        elif _env_pct > 30:
            lines.append(f"- 环境描写：实测占比 {_env_pct:.1f}%（偏高），严禁省略环境铺陈，氛围营造是核心风格")
    if _psych_pct is not None:
        if _psych_pct < 15:
            lines.append(f"- 纯心理描写：实测占比仅 {_psych_pct:.1f}%，连续纯心理不超过 2 句，情绪靠动作与对话暗示")
        elif _psych_pct > 40:
            lines.append(f"- 心理描写：实测占比 {_psych_pct:.1f}%（偏高），严禁完全省略内心刻画")
    if _short_rate is not None and _short_rate > 30:
        lines.append(f"- 长句连续：短句率 {_pct(sent.get('short_sent_ratio_pct'))}，禁止连续 3 句以上长句")
    if _dlg_ratio is not None and _dlg_ratio > 0.5:
        lines.append(f"- 纯叙事连续：对话占比 {_pct(dlg.get('dialogue_ratio_pct'))}，禁止连续 5 句以上纯叙事")
    if avg_sent is not None and avg_sent < 18:
        lines.append(f"- 句长上限：平均句长仅 {_num_out(avg_sent)} 字，禁止单句超过 25 字")
    if qst is not None and exl is not None and qst > exl * 2:
        lines.append(
            f"- 叹号代问号：问号 {_num_out(qst, 2)}/千字 远多于感叹号 {_num_out(exl, 2)}/千字，禁止用感叹号替代疑问表达")
    _assert_quantified_bans(lines)

    # 2. Dialogue norms + synthetic demos
    lines.append("\n## 对话规范与示范\n")
    lines.append("- 对话是信息传递而非闲聊：每句带有目的性（判断局势/揭示设定/塑造立场）")
    lines.append("- 动作从对话标签中剥离，单独成段描写\n")
    lines.append("【正确示范】\n" + _DEMO_CORRECT)
    lines.append("\n【错误示范】\n" + _DEMO_INCORRECT)
    # 自校验曾硬编码"正确示范：省略号 0、破折号 0、感叹号 0"和"对话标签仅用「问」「说」"，
    # 与铁律 4（实测密度允许这些标点）及实测 top 标签直接矛盾，会误导分身把活跃特征清零。
    # 示范文本是"形式样例"（只演示句式/标签/留白怎么用），不代表目标密度；
    # 密度一律以铁律 4 与量化禁令的实测基线为准。
    demo_tags = "、".join(f"「{t}」" for t in list(_tag_freqs)[:3]) if _tag_freqs else "「道」「说」"
    lines.append(
        f"\n【示范自校验】**注意：上方两段示范只演示写法形式（句式、标签、留白如何用），"
        f"其自身字数过短，不代表目标标点密度；正文写作时各类标点的用量一律以"
        f"铁律 4 与量化禁令给出的实测基线为准。**"
        f"\n- 正确示范要点：对话标签只用 {demo_tags} 中的主力标签、动作从标签剥离独立成段、"
        f"无修饰性标签堆叠；正文平均句长须落在 {_band(avg_sent, 0.85, 1.15, '字', 0)} 区间。"
        "\n- 错误示范违规点：修饰性标签堆叠、省略号在无迟疑处滥用、无信息量抒情"
        "（违规原因是「用错了地方」，不是「用了这个标点」——该标点在铁律 4 允许的用法内仍可使用）。"
    )

    # 2b. 通用 AI 味禁用词（归档 GENERIC_TABOO_PHRASES）。这些是从语料本身
    #     看不出「该少用」的书面连接词——它们是模型腔的通用指纹，与本文风无关，
    #     因此以固定清单出现，不依赖任何实测指标。
    lines.append("\n## 通用禁用词（AI 腔痕迹，一律禁用）\n")
    lines.append("以下书面连接词属于模型腔与公文腔，任何题材、任何场景都不得出现：\n")
    lines.append("、".join(f"「{p}」" for p in GENERIC_TABOO_PHRASES) + "。")
    lines.append("改写方向：删掉连接词让句子直接并列，或用具体动作、感官细节承担过渡。\n")

    # 3. Character voice reference — the desensitized voiceprint block.
    #    Keys are archetype labels (原型甲…), never real names: the persona is for
    #    writing new stories, so the point is carryable speech habits, not identity.
    voiceprint = report_json.get("voiceprint") or {}
    lines.append("\n## 角色声音参考（实测话术习惯）\n")
    if isinstance(voiceprint, dict) and voiceprint:
        lines.append("以下原型口吻由语料实测得出：为每个角色安排一套稳定的口吻，"
                     "同一角色跨场景保持一致，不同角色之间要有可辨识差异。\n")
        for label, vp in voiceprint.items():
            if not isinstance(vp, dict):
                continue
            tone = vp.get("tone_type") or _MISSING
            avg_len = _num(vp.get("avg_speech_len"))
            bits = [f"口吻类型：{tone}"]
            if avg_len is not None:
                bits.append(f"平均台词长度：{_num_out(avg_len, 1)} 字（{_band(avg_len, 0.7, 1.3, '字', 1)}）")
            tags = "、".join(f"「{t}」" for t in (vp.get("common_tags") or []) if t)
            if tags:
                bits.append(f"常用标签：{tags}")
            phrases = [p for p in (vp.get("catchphrases") or []) if p]
            if phrases:
                bits.append(f"口头禅：{'、'.join(f'「{p}」' for p in phrases)}")
            openers = [p for p in (vp.get("opening_words") or []) if p]
            if openers:
                bits.append(f"常见起句：{'、'.join(f'「{p}」' for p in openers)}")
            lines.append(f"### {label}\n- " + "\n- ".join(bits))
        lines.append("\n> 注意：上表是各原型的**相对差异**，用于区分角色；"
                     "全篇标点密度与句长仍以铁律 4 与量化禁令的实测基线为准。")
    else:
        lines.append("- （未取得可用的实测话术数据，按对话规范执行即可）")

    lines.append("\n## 技法调用指令\n")
    if cards:
        for idx, card in enumerate(cards, 1):
            cid = card.get("id", f"T{idx:02d}")
            lines.append(f"### [{cid}] {card.get('name', '技法')}")
            lines.append(f"- 触发：{card.get('trigger', '—')}")
            for s in card.get("steps", []):
                lines.append(f"- 执行：{s}")
            lines.append(f"- 边界：{card.get('boundary', '—')}")
    else:
        lines.append("- （依据上述铁律执行）")

    # 4. Macro thinking model
    lines.append("\n## 创作思维决策模型\n")
    key_map = [
        ("attention_order", "注意力顺序"),
        ("info_control", "信息控制"),
        ("conflict_escalation", "冲突升级"),
        ("cost_management", "代价管理"),
        ("closure", "收束方式"),
        ("long_arc", "长线布局"),
    ]
    for key, label in key_map:
        val = str(thinking.get(key, "")).strip() if isinstance(thinking, dict) else ""
        lines.append(f"- **{label}**：{val or '遵循正文风格自然推进'}")
    boundary = str(thinking.get("adaptation_boundary", "")).strip()
    if boundary:
        lines.append(f"- **题材适配边界**：{boundary}")

    if allow_author_identity:
        lines.append(f"\n> 本提示词由《{work_title}》定量测量数据自动生成，所有阈值为实测区间，偏离将破坏风格一致性。")
    else:
        lines.append("\n> 本提示词由脱敏风格测量数据自动生成，所有阈值为实测区间，偏离将破坏风格一致性。")
    return "\n".join(lines)
