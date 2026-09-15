# -*- coding: utf-8 -*-
"""跨期对比矩阵与演变量趋势。

归档版 `skill.py:224` 的 `compare_segments` 提供 6 维对比矩阵与趋势判定，迭代中
退化成了一份未成矩阵的 `era_window_metrics`。此模块把已有的 per-era 指标整理成
矩阵，并对每一维做趋势判定（上升/下降/波动/稳定）。

纯确定性、无 LLM：输入相同则输出相同，可写单元测试。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: 6 个对比维度： (维度名, 取值路径, 展示单位)
MATRIX_DIMENSIONS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("平均句长", ("sentence_structure", "avg_sent_len"), "字"),
    ("短句率", ("sentence_structure", "short_sent_ratio_pct"), "%"),
    ("长句率", ("sentence_structure", "long_sent_ratio_pct"), "%"),
    ("平均段长", ("paragraph_rhythm", "avg_para_len"), "字"),
    ("对话占比", ("dialogue_features", "dialogue_ratio_pct"), "%"),
    ("词汇丰富度", ("low_level_features", "vocabulary_richness", "ttr_filtered"), ""),
)

#: 趋势判定的相对波动阈值：峰谷差小于基线的该比例视为「稳定」。
_STABLE_CV = 0.10
#: 净变化 / 总路径长度 的比值下限：低于它说明来回震荡，不构成方向性趋势。
#: 只用斜率会把 [1,9,1,9] 判成「上升」（净变化为 0 但回归斜率非零），所以方向
#: 判定必须看净位移占总变化的比例，而不是拟合斜率。
_DIRECTIONALITY_MIN = 0.5


def _dig(source: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    current: Any = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _num(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_trend(values: List[float]) -> str:
    """上升 / 下降 / 波动 / 稳定 / 数据不足.

    Direction is judged by net displacement relative to total path length, not by
    a regression slope: ``[1, 9, 1, 9]`` backslides to its start, so calling it
    "rising" (which a bare slope does) would be plainly wrong.
    """
    if len(values) < 2:
        return "数据不足"
    baseline = sum(values) / len(values)
    if baseline == 0:
        return "稳定" if all(v == 0 for v in values) else "波动"
    spread = (max(values) - min(values)) / abs(baseline)
    if spread <= _STABLE_CV:
        return "稳定"
    net = values[-1] - values[0]
    path = sum(abs(values[i + 1] - values[i]) for i in range(len(values) - 1))
    if path and abs(net) / path >= _DIRECTIONALITY_MIN:
        return "上升" if net > 0 else "下降"
    return "波动"


def build_cross_era_matrix(era_window_metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """6-dimension matrix across eras plus a per-dimension trend."""
    windows = [w for w in (era_window_metrics or []) if isinstance(w, dict)]
    if not windows:
        return {"eras": [], "dimensions": [], "note": "未取得分期窗口指标"}

    eras = [str(w.get("era", "未分期")) for w in windows]
    dimensions: List[Dict[str, Any]] = []
    for name, path, unit in MATRIX_DIMENSIONS:
        values: List[Optional[float]] = [_num(_dig(w, path)) for w in windows]
        present = [v for v in values if v is not None]
        dimension: Dict[str, Any] = {
            "dimension": name,
            "unit": unit,
            "values": values,
        }
        if present:
            dimension["mean"] = round(sum(present) / len(present), 4)
            dimension["trend"] = classify_trend(present)
        else:
            dimension["mean"] = None
            dimension["trend"] = "数据不足"
        dimensions.append(dimension)

    return {
        "eras": eras,
        "dimensions": dimensions,
        "era_count": len(eras),
    }


# ---------------------------------------------------------------------------
# 语义子维度（可启发式测量的部分）
# ---------------------------------------------------------------------------
#: 对话功能四类（信息交换 / 冲突对抗 / 情感表达 / 日常闲聊）的关键词线索。
_DIALOGUE_FUNCTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("冲突对抗", ("住手", "休想", "滚", "该死", "退下", "放肆", "闭嘴", "给我", "放肆", "找死")),
    ("情感表达", ("爱你", "恨你", "想你", "抱歉", "对不起", "谢谢你", "舍不得", "心疼")),
    ("信息交换", ("为何", "何故", "如何", "什么", "是否", "难道", "莫非", "因为", "所以")),
    ("日常闲聊", ("吃过", "天气", "走吧", "好吧", "罢了", "罢了", "哈哈")),
)

#: POV 稳定性：第一人称/第三人称标志词
_FIRST_PERSON_MARKERS = ("我", "咱", "俺")
_THIRD_PERSON_MARKERS = ("他", "她", "它", "他们", "她们")


def _classify_dialogue_function(quote: str) -> str:
    for label, keywords in _DIALOGUE_FUNCTIONS:
        if any(kw in quote for kw in keywords):
            return label
    return "信息交换"


def measure_dialogue_functions(quotes: List[str]) -> Dict[str, Any]:
    """对话功能分布（启发式：关键词线索）。"""
    counts: Dict[str, int] = {label: 0 for label, _ in _DIALOGUE_FUNCTIONS}
    for quote in quotes or []:
        if not isinstance(quote, str) or not quote.strip():
            continue
        counts[_classify_dialogue_function(quote)] += 1
    total = sum(counts.values())
    distribution = {
        label: round(count / total, 4) if total else 0.0 for label, count in counts.items()
    }
    return {
        "counts": counts,
        "distribution": distribution,
        "total_quotes": total,
        "method": "keyword-heuristic",
    }


def measure_pov_stability(text: str) -> Dict[str, Any]:
    """POV 稳定性：第一/第三人称标志词计数与主导倾向。"""
    first = sum(text.count(m) for m in _FIRST_PERSON_MARKERS)
    third = sum(text.count(m) for m in _THIRD_PERSON_MARKERS)
    total = first + third
    if total == 0:
        return {"first_person_count": 0, "third_person_count": 0,
                "dominant_pov": "无数据", "stability": "无数据"}
    first_ratio = first / total
    if first_ratio > 0.6:
        dominant = "第一人称主导"
    elif first_ratio < 0.4:
        dominant = "第三人称主导"
    else:
        dominant = "混合视角"
    # 稳定性用少数派占比衡量：一方压倒另一方 = 稳定。
    stability = "稳定" if max(first_ratio, 1 - first_ratio) > 0.75 else "波动"
    return {
        "first_person_count": first,
        "third_person_count": third,
        "dominant_pov": dominant,
        "stability": stability,
        "method": "marker-count-heuristic",
    }


def build_semantic_dimensions(
    text: str,
    quotes: Optional[List[str]] = None,
    dialogue_functions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """聚合可启发式测量的语义子维度。

    情感强度趋势与更细的对话意图仍交由 LLM 在既有单次调用内产出（不新增轮次）；
    这里只给能确定性测量的部分。

    ``dialogue_functions`` 允许复用调用方已算好的分布：原始引语只在
    ``dialogue_analyzer`` 内部可见，若在此以空引语重算，公开产物会拿到一份恒为零
    的分布，与 ``dialogue_features`` 中的真实值自相矛盾。
    """
    if dialogue_functions is None:
        dialogue_functions = measure_dialogue_functions(quotes or [])
    return {
        "dialogue_functions": dialogue_functions,
        "pov_stability": measure_pov_stability(text or ""),
    }


# ---------------------------------------------------------------------------
# 正反例抽取（仅内部诊断，不进公开产物）
# ---------------------------------------------------------------------------
def extract_exemplars(
    quotes: List[Dict[str, Any]],
    max_items: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """按「像/不像」抽出正反例，供技能自检与内部诊断。

    刻意**不进入公开产物**：正例是原文片段，反例可能命中脱敏红线。返回值仅供
    调用方在私有路径使用（与 `include_raw_evidence` 同级）。
    """
    good: List[Dict[str, Any]] = []
    bad: List[Dict[str, Any]] = []
    for item in quotes or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        entry = {"chunk_id": item.get("chunk_id", ""), "text": text}
        # 反例信号：修饰性标签堆叠、省略号/感叹号滥用、无信息量抒情。
        decorative = sum(1 for t in ("低声道", "沉声道", "冷笑道", "娇笑道", "幽幽地") if t in text)
        if decorative >= 2 or text.count("…") >= 3 or text.count("！") >= 3:
            bad.append(entry)
        elif 6 <= len(text) <= 60:
            good.append(entry)
        if len(good) >= max_items and len(bad) >= max_items:
            break
    return {"exemplars_positive": good[:max_items], "exemplars_negative": bad[:max_items]}
