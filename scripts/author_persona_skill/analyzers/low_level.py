# -*- coding: utf-8 -*-
"""低层测量层：可读性、词汇丰富度、句法复杂度、情感、词长、词性、命名实体、世界观词汇。

归档版 v7.0.0 把这些放在 `text_analysis.py`（可读性四式 / TTR / hapax / 分句复杂度 /
词长 / 词性 / 实体）与 `style_analyzer.py`（世界观五类）。迭代中整体丢失，此模块
恢复它们，并做三处必要调整：

1. **不依赖 numpy**。归档用 `np.mean/np.median/np.std`，这里改用 stdlib
   `statistics`——numpy 归档里的 `.pyd` 是平台锁定的，无法跨平台内嵌。
2. **分词可降级**。所有需要分词的部分走 `analyzers.tokenizer` 适配层；缺 jieba 时
   降级为正则近似并整块标注 `degraded: True`（见 quality-baseline §4 的数据源分级）。
3. **句长阈值收敛为一处**。归档把 18/20/25/35 散落在多处，这里统一到
   `SENT_LEN_BANDS` 常量，避免同族阈值互相打架。
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from . import tokenizer

# ---------------------------------------------------------------------------
# 阈值：全模块唯一来源
# ---------------------------------------------------------------------------
#: 句长分档（字符）。归档散落多套阈值，此处收敛为一份。
SENT_LEN_BANDS: Tuple[Tuple[str, int], ...] = (
    ("极短", 10), ("短", 20), ("中", 30), ("长", 50),
)

#: 平均句长 → 风格分档描述。归档把 18/20/25/35 散落在多处，收敛于此。
#: (上界不含, 描述)；最后一项为兜底。
SENT_LEN_BRACKETS: Tuple[Tuple[Optional[float], str], ...] = (
    (18, "极短 (高频快节奏/碎片推进)"),
    (25.0 + 1e-9, "中短 (清晰利落/动势平稳)"),
    (35.0 + 1e-9, "中长 (稳健叙事/适度铺陈)"),
    (None, "长句 (绵密复杂/深度描摹)"),
)


def sent_len_bracket(avg_sent_len: Optional[float]) -> str:
    """Average sentence length → descriptor, from the single threshold table."""
    if avg_sent_len is None:
        return "无数据"
    for ceiling, label in SENT_LEN_BRACKETS:
        if ceiling is None or avg_sent_len < ceiling:
            return label
    return "无数据"

#: 复杂词阈值（字符数）。中文四字以上多为成语或复合词。
COMPLEX_WORD_MIN_CHARS = 4

_CLAUSE_SEPARATORS = re.compile(r"[，；：、,;:]")
_SUBORDINATE_MARKERS = re.compile(r"(因为|所以|虽然|但是|如果|那么|既然|因此|然而|不过|只是|只有|除非)")
_COORDINATE_MARKERS = re.compile(r"(和|与|而且|或者|还是|但|而)")
_SENT_SPLIT = re.compile(r"[。！？!?…]+")

# 情感词表（各约 40 条）。这是启发式测量，不是语义模型：只用于粗判正负倾向，
# 报告中必须以「倾向/疑似」表述（quality-baseline §4）。
_POSITIVE_WORDS = frozenset({
    "笑", "喜悦", "欢喜", "高兴", "开心", "快乐", "幸福", "温暖", "温柔", "甜蜜",
    "希望", "光明", "美好", "美丽", "善良", "感动", "感激", "骄傲", "得意", "欣慰",
    "安心", "平静", "宁静", "放松", "舒畅", "兴奋", "激动", "愉快", "欢快", "柔和",
    "亮堂", "鲜亮", "晴朗", "芬芳", "舒展", "坚定", "勇气", "勇敢", "胜利", "圆满",
})
_NEGATIVE_WORDS = frozenset({
    "哭", "悲", "悲伤", "悲痛", "痛苦", "苦涩", "绝望", "黑暗", "阴暗", "恐惧",
    "害怕", "惊恐", "愤怒", "恼火", "仇恨", "厌恶", "恶心", "孤独", "寂寞", "凄凉",
    "寒冷", "冰冷", "死", "死亡", "血", "伤口", "疼痛", "颤抖", "崩溃", "疲惫",
    "憔悴", "惨", "哀", "愁", "恨", "怒", "慌", "惧", "泪", "绝望", "无助",
})

#: 系统流关键词（世界观特色系统检测）
SPECIAL_SYSTEM_KEYWORDS = (
    "选项", "系统", "御兽", "修炼", "技能", "等级", "属性", "任务", "副本", "天赋",
)


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def split_sentences(text: str) -> List[str]:
    """Sentence split shared by every measurement here."""
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _token_list(text: str, words: Optional[List[str]] = None) -> List[str]:
    if words is not None:
        return words
    return [w for w in tokenizer.cut(text) if w.strip()]


# ---------------------------------------------------------------------------
# 可读性
# ---------------------------------------------------------------------------
def _classify_readability(avg_sent_len: float, avg_word_len: float, complex_ratio: float) -> str:
    """Three-factor readability level (归档 _classify_readability)."""
    score = 0
    if avg_sent_len < 15:
        score += 1
    elif avg_sent_len < 25:
        score += 2
    elif avg_sent_len < 40:
        score += 3
    else:
        score += 4

    if avg_word_len < 2:
        score += 1
    elif avg_word_len < 3:
        score += 2
    elif avg_word_len < 4:
        score += 3
    else:
        score += 4

    if complex_ratio < 0.1:
        score += 1
    elif complex_ratio < 0.2:
        score += 2
    elif complex_ratio < 0.3:
        score += 3
    else:
        score += 4

    avg_score = score / 3
    if avg_score < 1.5:
        return "简单"
    if avg_score < 2.5:
        return "中等"
    if avg_score < 3.5:
        return "较难"
    return "困难"


def measure_readability(
    text: str,
    sentences: Optional[List[str]] = None,
    words: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """四式可读性指数：杨承淑 / Flesch-Kincaid / Gunning-Fog / SMOG."""
    sentences = sentences if sentences is not None else split_sentences(text)
    words = _token_list(text, words)
    total_chars = len(text)
    n_sent = max(len(sentences), 1)
    n_words = max(len(words), 1)

    avg_sent_len = total_chars / n_sent
    word_lens = [len(w) for w in words if w.strip()]
    avg_word_len = (sum(word_lens) / len(word_lens)) if word_lens else 0.0

    complex_words = [w for w in words if len(w) >= COMPLEX_WORD_MIN_CHARS]
    complex_ratio = len(complex_words) / n_words

    # 杨承淑中文可读性指数（归档式，中文原生：句长以字计、复杂词比以词计）。
    yang = 0.4 * (avg_sent_len + 100 * complex_ratio)
    # Flesch-Kincaid：第二项在英文式中是「音节/词」。归档把「词/句」代入该项，
    # 且未除以平均音节，实测可产出 130 之类的无意义年级——按「旧版缺陷不予复制」
    # 修正为中文适配：字/句 + 字/词（中文字≈音节）。
    fk = max(0.0, 0.39 * avg_sent_len + 11.8 * avg_word_len - 15.59)
    # Gunning-Fog 的 ASL 按定义是「词/句」，与杨承淑式的「字/句」不同口径，
    # 归档把两式写成同一表达式属重复计量，此处各自回归本义。
    fog = 0.4 * (n_words / n_sent + 100 * complex_ratio)
    smog = 1.043 * (len(complex_words) / n_sent) ** 0.5 + 3.1291

    return {
        "yang_chengshu_index": round(yang, 2),
        "flesch_kincaid_grade": round(fk, 2),
        "gunning_fog_index": round(fog, 2),
        "smog_index": round(smog, 2),
        "avg_sentence_length_chars": round(avg_sent_len, 2),
        "avg_word_length_chars": round(avg_word_len, 2),
        "complex_word_count": len(complex_words),
        "complex_word_ratio": round(complex_ratio, 4),
        "readability_level": _classify_readability(avg_sent_len, avg_word_len, complex_ratio),
        "degraded": tokenizer.is_degraded(),
    }


# ---------------------------------------------------------------------------
# 词汇丰富度
# ---------------------------------------------------------------------------
def measure_vocabulary(text: str, words: Optional[List[str]] = None) -> Dict[str, Any]:
    """TTR / hapax / dis-legomena / 词频分布。"""
    words = _token_list(text, words)
    if not words:
        return {
            "total_words": 0, "unique_words": 0, "ttr": 0.0, "ttr_filtered": 0.0,
            "hapax_count": 0, "hapax_ratio": 0.0, "dis_legomena_count": 0,
            "multi_occurrence_count": 0, "top_words": [], "degraded": tokenizer.is_degraded(),
        }
    counts = Counter(words)
    unique = len(counts)
    total = len(words)
    hapax = sum(1 for c in counts.values() if c == 1)
    dis = sum(1 for c in counts.values() if c == 2)
    multi = sum(1 for c in counts.values() if c > 2)

    # ttr_filtered：剔除单字词与标点残留后的 TTR（归档 _build_style_dna_label 误用
    # 原始 ttr 的打分问题，这里给出更稳的口径供下游选择）。
    filtered = [w for w in words if len(w) >= 2]
    ttr_filtered = (len(set(filtered)) / len(filtered)) if filtered else 0.0

    return {
        "total_words": total,
        "unique_words": unique,
        "ttr": round(unique / max(total, 1), 4),
        "ttr_filtered": round(ttr_filtered, 4),
        "hapax_count": hapax,
        "hapax_ratio": round(hapax / max(unique, 1), 4),
        "dis_legomena_count": dis,
        "multi_occurrence_count": multi,
        "top_words": [w for w, _ in counts.most_common(20) if len(w.strip()) > 1][:20],
        "degraded": tokenizer.is_degraded(),
    }


# ---------------------------------------------------------------------------
# 句法复杂度
# ---------------------------------------------------------------------------
def _classify_complexity(avg_clauses: float) -> str:
    if avg_clauses < 1.5:
        return "简单句主导"
    if avg_clauses < 2.5:
        return "轻度复合"
    if avg_clauses < 3.5:
        return "复合句偏多"
    return "复杂长句主导"


def measure_sentence_complexity(text: str, sentences: Optional[List[str]] = None) -> Dict[str, Any]:
    """分句数、从属/并列比例、复杂度分级。"""
    sentences = sentences if sentences is not None else split_sentences(text)
    if not sentences:
        return {
            "avg_clauses_per_sentence": 0.0, "max_clauses_in_sentence": 0,
            "subordinate_ratio": 0.0, "coordinate_ratio": 0.0,
            "complexity_level": "无数据", "degraded": tokenizer.is_degraded(),
        }
    total_clauses = 0
    subordinate = 0
    coordinate = 0
    max_clauses = 0
    for sent in sentences:
        clauses = [c for c in _CLAUSE_SEPARATORS.split(sent) if c.strip()]
        n = max(len(clauses), 1)
        total_clauses += n
        max_clauses = max(max_clauses, n)
        subordinate += len(_SUBORDINATE_MARKERS.findall(sent))
        coordinate += len(_COORDINATE_MARKERS.findall(sent))
    avg_clauses = total_clauses / len(sentences)
    return {
        "avg_clauses_per_sentence": round(avg_clauses, 2),
        "max_clauses_in_sentence": max_clauses,
        "subordinate_clause_count": subordinate,
        "coordinate_clause_count": coordinate,
        "subordinate_ratio": round(subordinate / max(total_clauses, 1), 4),
        "coordinate_ratio": round(coordinate / max(total_clauses, 1), 4),
        "complexity_level": _classify_complexity(avg_clauses),
        "degraded": tokenizer.is_degraded(),
    }


# ---------------------------------------------------------------------------
# 情感
# ---------------------------------------------------------------------------
def measure_sentiment(text: str) -> Dict[str, Any]:
    """词表法情感倾向（启发式：负值偏阴郁，正值偏明亮）。"""
    pos = sum(1 for w in _POSITIVE_WORDS if w in text)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in text)
    total = pos + neg
    balance = ((pos - neg) / total) if total else 0.0
    if balance > 0.2:
        tone = "偏正向"
    elif balance < -0.2:
        tone = "偏负向"
    else:
        tone = "中性"
    return {
        "positive_hits": pos,
        "negative_hits": neg,
        "sentiment_balance": round(balance, 4),
        "dominant_tone": tone,
        "method": "wordlist-heuristic",
    }


# ---------------------------------------------------------------------------
# 词长分布
# ---------------------------------------------------------------------------
def measure_word_length(text: str, words: Optional[List[str]] = None) -> Dict[str, Any]:
    """1 / 2 / 3 / 4+ 字词比例。"""
    words = [w.strip() for w in _token_list(text, words) if w.strip()]
    if not words:
        return {"len_1_ratio": 0.0, "len_2_ratio": 0.0, "len_3_ratio": 0.0,
                "len_4plus_ratio": 0.0, "degraded": tokenizer.is_degraded()}
    buckets = {1: 0, 2: 0, 3: 0}
    four_plus = 0
    for w in words:
        n = len(w)
        if n in buckets:
            buckets[n] += 1
        else:
            four_plus += 1
    total = len(words)
    return {
        "len_1_ratio": round(buckets[1] / total, 4),
        "len_2_ratio": round(buckets[2] / total, 4),
        "len_3_ratio": round(buckets[3] / total, 4),
        "len_4plus_ratio": round(four_plus / total, 4),
        "degraded": tokenizer.is_degraded(),
    }


# ---------------------------------------------------------------------------
# 词性分布
# ---------------------------------------------------------------------------
_POS_MAPPING = {
    "n": "noun", "nr": "person_name", "ns": "place_name", "nt": "org_name",
    "nz": "other_noun", "v": "verb", "vd": "verb", "vn": "verb",
    "a": "adjective", "ad": "adjective", "an": "adjective",
    "d": "adverb", "r": "pronoun", "m": "numeral",
    "q": "quantity", "u": "particle", "c": "conjunction",
    "p": "preposition", "x": "other",
}
#: Prefix → category, matched longest-first so ``nr`` beats ``n``.
_POS_PREFIXES = ("nr", "ns", "nt", "nz", "vd", "vn", "ad", "an", "n", "v", "a", "d",
                 "r", "m", "q", "u", "c", "p", "x")


def _pos_category(flag: str) -> str:
    for prefix in _POS_PREFIXES:
        if flag.startswith(prefix):
            return _POS_MAPPING.get(prefix, "other")
    return "other"


def measure_pos_distribution(text: str, pairs: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Any]:
    """名/动/形/副 占比（分母为实词总数，与归档 `_pos_distribution` 一致）。

    四项占比之和为 1，可直接读作实词构成；``content_word_ratio`` 另以**全部
    token**（含标点/x 类）为分母，两条口径不同，不可混用。
    """
    pairs = tokenizer.posseg(text) if pairs is None else pairs
    if not pairs:
        return {"noun_ratio": 0.0, "verb_ratio": 0.0, "adjective_ratio": 0.0,
                "adverb_ratio": 0.0, "content_word_ratio": 0.0,
                "degraded": tokenizer.is_degraded()}
    counter: Counter[str] = Counter()
    content = 0
    tokens = 0
    for word, flag in pairs:
        if not word.strip():
            continue
        tokens += 1
        category = _pos_category(flag)
        counter[category] += 1
        if category in ("noun", "verb", "adjective", "adverb"):
            content += 1
    if not tokens or not content:
        return {"noun_ratio": 0.0, "verb_ratio": 0.0, "adjective_ratio": 0.0,
                "adverb_ratio": 0.0, "content_word_ratio": 0.0,
                "degraded": tokenizer.is_degraded()}
    return {
        "noun_ratio": round(counter["noun"] / content, 4),
        "verb_ratio": round(counter["verb"] / content, 4),
        "adjective_ratio": round(counter["adjective"] / content, 4),
        "adverb_ratio": round(counter["adverb"] / content, 4),
        "content_word_ratio": round(content / tokens, 4),
        "content_word_count": content,
        "degraded": tokenizer.is_degraded(),
    }


# ---------------------------------------------------------------------------
# 命名实体
# ---------------------------------------------------------------------------
def measure_named_entities(text: str, pairs: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Any]:
    """人名 / 地名 / 机构名 / 其他专名 计数与密度。

    注意：实体样例词是**原文专名**，属于身份轨迹，公开产物必须走映射或剔除
    （renderer 的敏感键剔除负责）。这里只提供诊断数据。
    """
    pairs = tokenizer.posseg(text) if pairs is None else pairs
    counts = {"person": 0, "place": 0, "org": 0, "other": 0}
    samples: Dict[str, List[str]] = {"person": [], "place": [], "org": [], "other": []}
    pos_to_entity = {"nr": "person", "ns": "place", "nt": "org", "nz": "other"}
    total = 0
    for word, flag in pairs:
        if not word.strip():
            continue
        total += 1
        key = next((k for k in ("nr", "ns", "nt", "nz") if flag.startswith(k)), None)
        if not key:
            continue
        entity = pos_to_entity[key]
        counts[entity] += 1
        if word not in samples[entity] and len(samples[entity]) < 10:
            samples[entity].append(word)
    total_entities = sum(counts.values())
    return {
        "person_count": counts["person"],
        "place_count": counts["place"],
        "org_count": counts["org"],
        "other_count": counts["other"],
        "total_entities": total_entities,
        "entity_density": round(total_entities / max(total, 1), 4),
        "sample_persons": samples["person"],
        "sample_places": samples["place"],
        "sample_orgs": samples["org"],
        "degraded": tokenizer.is_degraded(),
    }


# ---------------------------------------------------------------------------
# 世界观五类 + 特色系统
# ---------------------------------------------------------------------------
_WORLDVIEW_CATEGORIES = (
    ("核心角色", "nr"),
    ("核心设定", "nz"),
    ("力量体系", "nz"),
    ("组织势力", "nz"),
    ("地域场景", "ns"),
)


def extract_worldview_vocab(
    text: str,
    max_per_category: int = 10,
    pairs: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """五类世界观词汇分类（归档 _extract_worldview_vocab）。

    门槛与原版一致：``count > 5 且 len >= 2``。后三类同用 ``nz`` 词性，因此按
    类别顺序依次占用——先到先得，同一词只归一类。
    """
    pairs = tokenizer.posseg(text) if pairs is None else pairs
    # 词频必须从 **token 序列**统计；词性查表才用去重字典（一词一性）。
    # 两者混用会退化成「每个词恰好出现一次」，门槛 count>5 永远不成立，
    # 五类分类因此恒为空——归档版正是分成 counts 与 word_pos_map 两份。
    counts: Counter = Counter()
    word_pos: Dict[str, str] = {}
    for word, flag in pairs:
        w = word.strip()
        if not w or len(w) < 2:
            continue
        counts[w] += 1
        if w not in word_pos:
            word_pos[w] = flag

    high_freq = {w: c for w, c in counts.items() if c > 5}

    categorized: Dict[str, Dict[str, int]] = {cat: {} for cat, _ in _WORLDVIEW_CATEGORIES}
    used: set = set()
    for word, _ in sorted(high_freq.items(), key=lambda kv: (-kv[1], kv[0])):
        flag = word_pos.get(word, "")
        for cat, expected in _WORLDVIEW_CATEGORIES:
            if flag.startswith(expected) and word not in used and len(categorized[cat]) < max_per_category:
                categorized[cat][word] = counts[word]
                used.add(word)
                break

    # 归类结果是**原文专名**（nr/nz/ns），属于身份轨迹。公开产物只保留类别名与
    # 条数，词汇表由 renderer 的敏感键剔除移除（键名 term_counts 专为此设，不用
    # 泛化的 words 以免误伤未来新增字段）。`count` 显式冗余一份：term_counts 被
    # 剔除后，公开侧仍需知道「该类命中了几个」，否则附录只能显示「未达门槛」。
    categories = [
        {"category": cat, "count": len(categorized[cat]), "term_counts": categorized[cat]}
        for cat, _ in _WORLDVIEW_CATEGORIES if categorized[cat]
    ]
    return {
        "categories": categories,
        "special_systems": detect_special_systems(text),
    }


def detect_special_systems(text: str) -> List[str]:
    """系统流关键词命中（选项/系统/御兽/修炼/技能/等级/属性/任务/副本/天赋）。"""
    return [kw for kw in SPECIAL_SYSTEM_KEYWORDS if kw in text]


# ---------------------------------------------------------------------------
# 聚合入口
# ---------------------------------------------------------------------------
def analyze_low_level(text: str) -> Dict[str, Any]:
    """Run every low-level measurement once and return one block.

    The corpus is tokenized exactly twice (word cut + POS tag) and the results are
    threaded through every sub-measurement: jieba on a 150k-char corpus costs
    seconds, and re-cutting per metric multiplied that by six.
    """
    return _analyze(text)[0]


def analyze_low_level_with_worldview(text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Low-level block + worldview classification sharing one tokenization pass.

    The style analyzer needs both; splitting them would tokenize the corpus twice.
    """
    return _analyze(text)


def _analyze(text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    sentences = split_sentences(text)
    words = _token_list(text)
    pairs = tokenizer.posseg(text)
    stats: Dict[str, Any] = {}
    lengths = [len(s) for s in sentences]
    if lengths:
        stats = {
            "avg_sent_len": round(statistics.fmean(lengths), 2),
            "median_sent_len": round(statistics.median(lengths), 2),
            "std_sent_len": round(statistics.pstdev(lengths), 2) if len(lengths) > 1 else 0.0,
            "max_sent_len": max(lengths),
            "min_sent_len": min(lengths),
        }
    low = {
        "readability": measure_readability(text, sentences, words),
        "vocabulary_richness": measure_vocabulary(text, words),
        "sentence_complexity": measure_sentence_complexity(text, sentences),
        "sentiment": measure_sentiment(text),
        "word_length_distribution": measure_word_length(text, words),
        "pos_distribution": measure_pos_distribution(text, pairs),
        "named_entities": measure_named_entities(text, pairs),
        "sent_len_stats": stats,
        "tokenizer": tokenizer.tokenizer_status(),
    }
    return low, extract_worldview_vocab(text, pairs=pairs)


def classify_sent_len(value: Optional[float]) -> str:
    """Single-source sentence-length banding (归档散落 18/20/25/35 的收敛点)."""
    if value is None:
        return "无数据"
    for label, ceiling in SENT_LEN_BANDS:
        if value < ceiling:
            return label
    return "超长"
