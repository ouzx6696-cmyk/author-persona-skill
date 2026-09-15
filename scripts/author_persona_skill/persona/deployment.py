# -*- coding: utf-8 -*-
"""平台部署配置（温度与 max_tokens 推荐值）。

归档版 v7.0.0 的 `build_deployment_config` 按实测风格特征动态给出采样温度：
短句率高 → 温度上调（节奏越碎、越需要创意发散）；感叹号密度高 → 再 +0.05。
公式原样保留，只把输入的指标键换成本技能的实测结构。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_deployment_config(quant: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Derive per-platform sampling params from measured features.

    Formula (ported verbatim from the archive):
      short_rate > 25  → 0.85 + min(0.10, (short_rate-25)*0.004)
      15 ≤ short ≤ 25  → 0.75 + (short_rate-15)*0.01
      short_rate < 15  → 0.70 + short_rate*0.005
      clamp to [0.65, 0.95]; +0.05 when exclamation density > 8/千字.
    """
    base: Dict[str, Any] = {
        "platforms": {
            "dify": {"temperature": 0.8, "max_tokens": 4096, "config_location": "System Prompt"},
            "coze": {"temperature": 0.8, "top_p": 0.9, "config_location": "人设与回复逻辑 > 人设词"},
            "solo": {"temperature": 0.8, "max_tokens": 4096, "config_location": "System Prompt"},
            "chatgpt": {"temperature": 0.8, "config_location": "Custom Instructions / System"},
            "claude": {"temperature": 0.8, "config_location": "System Prompt"},
        },
        "config_note": "温度建议设置在0.7-0.9之间。如果需要更严谨的剧情逻辑，可降低至0.6-0.7。",
    }
    quant = quant or {}
    sent = quant.get("sentence_structure", {}) or {}
    dlg = quant.get("dialogue_features", {}) or {}
    punc = quant.get("punctuation_density", {}) or {}

    # 实测口径：short_sent_ratio_pct 是百分比字符串，先归一到 0–100 数值。
    short_rate = _num(sent.get("short_sent_ratio")) 
    if short_rate is None:
        pct = sent.get("short_sent_ratio_pct")
        short_rate = _num(str(pct).rstrip("%")) if pct is not None else None
    short_rate = short_rate if short_rate is not None else 0.0
    if short_rate <= 1.0:
        # 归一化比例（0–1）与百分比（0–100）两种口径都要能接住。
        short_rate *= 100.0

    exclaim = _num(punc.get("exclamation")) or 0.0
    dialogue_ratio = _num(dlg.get("dialogue_ratio")) or 0.0
    d_n_ratio = dialogue_ratio / max(1e-6, 1.0 - dialogue_ratio)
    dialogue_count = _num(dlg.get("total_quotes")) or 0.0

    if short_rate > 25:
        temp = 0.85 + min(0.10, (short_rate - 25) * 0.004)
    elif short_rate >= 15:
        temp = 0.75 + (short_rate - 15) * 0.01
    else:
        temp = 0.7 + short_rate * 0.005
    temp = round(min(0.95, max(0.65, temp)), 2)
    if exclaim > 8:
        temp = min(0.95, round(temp + 0.05, 2))

    max_tokens = 4096
    if d_n_ratio > 0.8 or dialogue_count > 1000:
        max_tokens = 6144
    if d_n_ratio > 1.2 or dialogue_count > 3000:
        max_tokens = 8192

    for platform in base["platforms"]:
        base["platforms"][platform]["temperature"] = temp
        if platform in ("dify", "solo"):
            base["platforms"][platform]["max_tokens"] = max_tokens

    if temp > 0.85:
        base["config_note"] = f"温度建议{temp}，轻松搞笑类作品适合较高温度，保持创意和幽默感。"
    elif temp < 0.75:
        base["config_note"] = f"温度建议{temp}，严肃/推理类作品适合较低温度，保持逻辑严谨。"
    else:
        base["config_note"] = f"温度建议{temp}，均衡型作品，保持创意与逻辑的平衡。"

    base["derived_from"] = {
        "short_sent_ratio_pct": round(short_rate, 2),
        "exclamation_per_kchars": round(exclaim, 2),
        "dialogue_ratio": round(dialogue_ratio, 4),
        "total_quotes": int(dialogue_count),
    }
    return base
