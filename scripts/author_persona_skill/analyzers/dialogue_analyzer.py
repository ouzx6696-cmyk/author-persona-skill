# -*- coding: utf-8 -*-
"""Dialogue extraction with tag whitelists/blacklists and speaker voiceprint statistics."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from .cross_era import measure_dialogue_functions

from . import tokenizer


TAG_WHITELIST = {
    "道", "说", "问", "答", "喊", "笑", "喝", "叹", "骂", "吼", "嘟囔", "嘀咕", "自语", "心道",
    "沉吟", "冷笑", "轻语", "怒吼", "低语", "轻声", "点头", "摇头", "皱眉", "抱拳", "拱手", "呵斥",
    "赞道", "叹道", "笑道", "怒道", "奇道", "喜道", "喝道", "骂道", "叫道", "问道", "答道", "说道",
    "嗔道", "冷声道", "淡笑道", "沉声道", "失声道", "惊呼道", "喃喃道", "大喝道", "娇笑道", "冷笑道",
}

TAG_BLACKLIST = {
    "写道", "报道", "知道", "味道", "管道", "频道", "古道", "王道", "霸道", "地道", "公道", "索道",
    "门道", "大道", "通道", "世道", "乐道", "头头是道", "微不足道", "津津乐道", "瞎说", "胡说",
    "传说", "听听说说", "解说", "评说", "小说", "话说", "按理说", "一般来说", "虽说", "假说", "学说",
    "听说", "可说", "不用说", "别说", "好说", "难说", "明说", "细说", "直说",
}

NON_NAME_TERMS = {
    # Places / Locations
    "黄河", "长江", "泰山", "昆仑", "华山", "嵩山", "衡山", "恒山", "终南山", "街道", "广场", "房间",
    "大殿", "密室", "森林", "湖泊", "山谷", "洞穴", "城市", "城门", "窗外", "门外", "虚空", "苍穹",
    "天地", "四周", "远处", "附近", "身后", "眼前", "背后", "空中", "地下", "水底", "深渊",
    # Generic Objects / Nouns
    "汽车", "飞机", "火车", "手机", "电脑", "宝剑", "长枪", "战刀", "铠甲", "戒指", "玉佩", "灵草",
    "丹药", "石头", "木头", "茶杯", "桌子", "椅子", "狂风", "暴雨", "闪电", "雷霆", "光芒", "黑夜",
    # Pronouns & determiners
    "这个", "那个", "一个", "几个", "很多", "所有", "一切", "他们", "她们", "它们", "我们", "你们",
    "自己", "有人", "谁也", "谁都", "何人", "为何", "众人", "大家", "属下", "在下", "老夫", "弟子",
    # Anaphora / reference words that must never become speaker names
    "后者", "前者", "对方", "此人", "来人", "那人", "这人", "两人", "三人", "四人",
    # Narration openers that precede tags without a speaker
    "毫无疑", "毫无", "显然", "当然", "总之", "此时", "随即", "于是", "接着", "然后",
    "最后", "另外", "此外", "同时", "事实上", "实际上", "要知道", "不得不说", "可以说",
}

# Speaker candidates that are pure pronouns after normalization are dropped.
PRONOUN_SPEAKER_BLOCKLIST = {"她", "他", "它", "她俩", "他俩"}

# Trailing action/verb suffixes glued to names by window scanning (罗兰点/雷克斯苦).
# Single source of truth shared with distill.desensitize._clean_speaker — do not
# fork a local copy; sorted longest-first so greedy stripping is deterministic.
SPEAKER_VERB_SUFFIXES = sorted(
    {
        "冷笑", "大笑", "微笑", "苦笑", "惨笑", "狂笑", "淡笑", "沉吟", "点头", "摇头",
        "皱眉", "喃喃", "嘀咕", "嘟囔", "轻声", "低声", "高声", "沉声", "厉声", "缓缓",
        "自语", "沉思", "怒喝", "大喝",
        "叹道", "笑道", "怒道", "问道", "答道", "说道", "喝道", "叫道", "喊道",
        "吩咐", "打断", "反问", "回答", "追问", "接口", "接话", "附和", "安慰", "催促",
        "摊手", "挑眉", "撇嘴", "咬牙",
        "并", "却", "便", "只", "又", "也", "忙", "写", "心", "暗", "微", "应", "接",
        "挑", "抬", "耸", "摊", "咧", "抿", "撇", "瞪", "怒", "喜",
        "苦", "叹", "惊", "急", "问", "答", "回", "想", "点", "摇", "笑", "摆", "说", "道",
    },
    key=len,
    reverse=True,
)

_NAME_CHARS_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z·]{2,6}$")

# Adverbial tails glued between a name and its dialogue tag
# ("弗朗茨[无奈]的说道" / "苏菲夫人[想了想]说道").
_ADVERB_TAILS = sorted(
    [
        "哈哈大笑", "微微一笑", "沉吟片刻", "沉默片刻", "深吸一口气", "斩钉截铁",
        "毫不犹豫", "开门见山", "胸有成竹", "不动声色", "若无其事", "一本正经",
        "郑重其事", "想了想", "想了下", "点了点头", "点了点", "点点头", "摇了摇头",
        "摇摇头", "顿了顿", "笑了笑", "叹了口气", "松了口气", "皱着眉头", "挑了挑眉",
        "无奈", "严肃", "认真", "平静", "淡定", "冷静", "沉重", "凝重", "诚恳",
        "关切", "关心", "好奇", "疑惑", "诧异", "惊讶", "震惊", "愤怒", "恼怒",
        "不满", "失望", "欣慰", "得意", "兴奋", "激动", "紧张", "焦急", "忧虑",
        "迟疑", "犹豫", "坚决", "果断", "连忙", "急忙", "赶忙", "慌忙", "立即",
        "立刻", "马上", "随即", "忽然", "突然", "渐渐", "缓缓", "慢慢", "轻轻",
        "淡淡", "微微", "低声", "轻声", "沉声", "冷声", "厉声", "高声", "大声",
        "朗声", "柔声", "小声", "开口", "继续", "接着", "然后", "最后", "再次",
        "依旧", "仍然",
    ],
    key=len,
    reverse=True,
)


def strip_adverb_tail(raw: str) -> str:
    """Strip adverbial/particle tails from a speaker candidate."""
    s = raw.strip()
    changed = True
    while changed and len(s) >= 4:
        changed = False
        m = re.match(r"^(.*?)(?:的|地|着)$", s)
        if m and len(m.group(1)) >= 3:
            s = m.group(1)
            changed = True
            continue
        for adv in _ADVERB_TAILS:
            if s.endswith(adv) and len(s) - len(adv) >= 2:
                s = s[: -len(adv)]
                changed = True
                break
    return s


def _accept_speaker_candidate(candidate: str) -> Optional[str]:
    """Validate a cleaned candidate string as a plausible speaker name."""
    if not (2 <= len(candidate) <= 4):
        return None
    if candidate in NON_NAME_TERMS:
        return None
    if any(c in candidate for c in "的了吗是在有和就个也这那都很到上过得着"):
        return None
    return candidate


def normalize_speaker_name(raw: str) -> str:
    """Clean a raw speaker candidate: strip quote/punct debris and glued verbs."""
    name = raw.strip("“”\"'「」『』…—，。！？!:：;；,、 ")
    changed = True
    while changed and len(name) > 2:
        changed = False
        for suffix in SPEAKER_VERB_SUFFIXES:
            if name.endswith(suffix) and len(name) - len(suffix) >= 2:
                name = name[: -len(suffix)]
                changed = True
                break
    return name


def is_plausible_speaker(name: str) -> bool:
    """Final gate for a normalized speaker name."""
    if not name or name in PRONOUN_SPEAKER_BLOCKLIST or name in NON_NAME_TERMS:
        return False
    # Pronoun-led two-char fragments (她摇/他想) that survived length guards.
    if len(name) == 2 and name[0] in "她他它":
        return False
    if any(c in name for c in "的了吗呢吧啊呀哦嘛"):
        return False
    return bool(_NAME_CHARS_RE.match(name))


class DialogueAnalyzer:
    """Analyzes dialogues, speaker statistics, and voiceprints from novel text."""

    def __init__(self, tag_window: int = 12):
        self.tag_window = tag_window
        # Dialogue quotation pattern: open and close classes each accept both
        # curly and corner brackets, so 「…」 pairs match the same way “…” do.
        self.quote_pattern = re.compile(r'[“"「]([\s\S]*?)[”"」]')

    # ------------------------------------------------------------------
    # Voiceprint helpers: per-speaker speech habits.
    #
    # These describe *how a character talks* (tone, catchphrases, sentence
    # openers), which is what lets section 1.9 and the `dialogue_review` block
    # be grounded in measurement instead of invented archetypes.
    # ------------------------------------------------------------------

    def _classify_tone(self, quotes: List[str]) -> str:
        """Classify a speaker's register by how their lines terminate.

        Question-led speech (>30% ending in ？) reads as 疑问型; exclamatory
        speech (>20% ending in ！) as 命令型; everything else is 陈述型.
        """
        total = 0
        question_count = 0
        exclamation_count = 0
        for text in quotes:
            stripped = text.strip()
            if not stripped:
                continue
            total += 1
            last_char = stripped[-1]
            if last_char in ("?", "？"):
                question_count += 1
            elif last_char in ("!", "！"):
                exclamation_count += 1
        if total == 0:
            return "陈述型"
        if question_count / total > 0.3:
            return "疑问型"
        if exclamation_count / total > 0.2:
            return "命令型"
        return "陈述型"

    def _extract_fixed_phrases(self, quotes: List[str]) -> List[str]:
        """High-frequency multi-character phrases a speaker reaches for often.

        Frequency alone is a weak signal with small samples, so the floor scales
        with the speaker's line count (``max(2, n // 10)``): a character with 40
        lines must repeat a phrase at least 4 times before it counts as a habit.
        """
        if not quotes:
            return []
        words = tokenizer.cut(" ".join(quotes))
        counter = Counter(word for word in words if len(word.strip()) >= 2)
        if not counter:
            return []
        min_freq = max(2, len(quotes) // 10)
        return [
            word for word, freq in counter.most_common(30)
            if freq >= min_freq
        ][:10]

    def _count_opening_words(self, quotes: List[str]) -> List[str]:
        """Words a speaker habitually opens their lines with."""
        counter: Counter[str] = Counter()
        for text in quotes:
            stripped = text.strip()
            if not stripped:
                continue
            words = tokenizer.cut(stripped)
            if words and len(words[0].strip()) >= 2:
                counter[words[0].strip()] += 1
        if not counter:
            return []
        min_freq = max(2, len(quotes) // 15)
        return [word for word, freq in counter.most_common(10) if freq >= min_freq]

    def extract_dialogues(self, text: str, chapters: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Extract dialogue segments, speaker tags, and distinguish high vs low confidence speakers.
        """
        raw_quotes: List[str] = []
        dialogue_chars = 0
        total_chars = max(len(text), 1)

        # 1. Extract all quotes
        quote_matches: List[Tuple[int, int, str]] = []
        for m in self.quote_pattern.finditer(text):
            content = m.group(1).strip()
            if content:
                quote_matches.append((m.start(), m.end(), content))
                raw_quotes.append(content)
                dialogue_chars += len(content)

        dialogue_ratio = dialogue_chars / total_chars

        # Tag frequency tracking
        tag_counts: Counter[str] = Counter()
        speaker_occurrences: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        speaker_chapters: Dict[str, Set[int]] = defaultdict(set)

        # Determine chapter boundaries if provided or auto-detect
        chap_boundaries = []
        if chapters:
            for idx, c in enumerate(chapters):
                chap_boundaries.append((idx, c.get("start", 0), c.get("end", len(text))))
        else:
            # Auto-detect chapter headings in text
            chapter_matches = [m.start() for m in re.finditer(r'^\s*(?:第[0-9零一二两三四五六七八九十百千万]+[章节回卷折篇]|卷[0-9零一二两三四五六七八九十百千万]+|序章|楔子|尾声|终章)', text, re.MULTILINE)]
            if len(chapter_matches) >= 2:
                for i in range(len(chapter_matches)):
                    start_p = chapter_matches[i]
                    end_p = chapter_matches[i + 1] if i + 1 < len(chapter_matches) else len(text)
                    chap_boundaries.append((i, start_p, end_p))

        def get_chapter_idx(pos: int) -> int:
            if not chap_boundaries:
                # Estimate chapter by 1000 chars blocks or default
                return pos // 1000
            for c_idx, start_pos, end_pos in chap_boundaries:
                if start_pos <= pos < end_pos:
                    return c_idx
            # Clamp positions outside every known span. Returning len(x) - 1
            # produced -1 for an empty boundary list, which collapsed every
            # quote into one pseudo-chapter and made the "across >= 2 chapters"
            # high-confidence test unsatisfiable for every speaker.
            if pos < chap_boundaries[0][1]:
                return chap_boundaries[0][0]
            return chap_boundaries[-1][0]

        # 2. Window scanning for speakers & tags around quotes
        for start_pos, end_pos, quote_text in quote_matches:
            c_idx = get_chapter_idx(start_pos)

            # Look in left window (before quote) and right window (after quote)
            left_window = text[max(0, start_pos - self.tag_window):start_pos].strip()
            right_window = text[end_pos:min(len(text), end_pos + self.tag_window)].strip()

            detected_speaker: Optional[str] = None
            detected_tag: Optional[str] = None

            # Helper to inspect candidate text window
            def parse_window(win: str) -> Tuple[Optional[str], Optional[str]]:
                # Check blacklist first to exclude false tags like "写道"
                for bad in TAG_BLACKLIST:
                    if bad in win:
                        return None, None

                # Check whitelist tags
                # 长标签优先；同长度按字典序定序——TAG_WHITELIST 是 set，
                # 若只按 len 排序，同长度标签的顺序随 PYTHONHASHSEED 漂移，
                # 会让 dao_shuo_ratio / tag_frequencies 在进程间不可复现。
                for tag in sorted(TAG_WHITELIST, key=lambda t: (-len(t), t)):
                    if tag in win:
                        tag_idx = win.find(tag)
                        candidate_name = win[:tag_idx].strip()

                        # Clean candidate name
                        candidate_name = re.sub(r'^[，。！？…—\s]+|[，。！？…—\s]+$', '', candidate_name)
                        # Remove leading stop words
                        candidate_name = re.sub(r'^(?:在|向|对|朝|冲|随着|只听|听到|忽听|便听|却见|只见)', '', candidate_name).strip()

                        speaker = _accept_speaker_candidate(candidate_name)
                        if speaker:
                            return speaker, tag
                        # Adverb-infix pattern: 名字+状语+(的/地/着)+tag，
                        # e.g. "弗朗茨无奈的说道" / "苏菲夫人想了想说道"。
                        stripped = strip_adverb_tail(candidate_name)
                        if stripped != candidate_name:
                            speaker = _accept_speaker_candidate(stripped)
                            if speaker:
                                return speaker, tag
                        return None, tag
                return None, None

            # Try left window then right window
            sp_left, tag_left = parse_window(left_window)
            sp_right, tag_right = parse_window(right_window)

            if sp_left:
                detected_speaker = sp_left
                detected_tag = tag_left
            elif sp_right:
                detected_speaker = sp_right
                detected_tag = tag_right
            else:
                detected_tag = tag_left or tag_right

            if detected_tag:
                tag_counts[detected_tag] += 1

            if detected_speaker:
                speaker_occurrences[detected_speaker].append({
                    "quote": quote_text[:50],
                    # Full line kept privately for voiceprint statistics; it never
                    # reaches a public artifact (renderer strips sample_quotes and
                    # the voiceprint block carries only mapped/neutral values).
                    "text": quote_text,
                    "tag": detected_tag or "道",
                    "chapter": c_idx,
                })
                speaker_chapters[detected_speaker].add(c_idx)

        # 3. Normalize & merge speaker names, then classify high vs low confidence.
        # Raw window-scanned names carry glued verbs (罗兰点) and anaphora (她摇);
        # normalization strips verbs, drops pronouns, and merges aliases into the
        # dominant surface form.
        canonical_occs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        canonical_chapters: Dict[str, Set[int]] = defaultdict(set)
        alias_trace: Dict[str, Set[str]] = defaultdict(set)
        surface_counts: Dict[str, int] = Counter()

        for raw_name, occs in speaker_occurrences.items():
            name = normalize_speaker_name(raw_name)
            if not is_plausible_speaker(name):
                continue
            canonical_occs[name].extend(occs)
            canonical_chapters[name].update(speaker_chapters.get(raw_name, set()))
            if name != raw_name:
                alias_trace[name].add(raw_name)
            surface_counts[name] += len(occs)

        # No prefix-based alias merging is performed here: aliases that normalize
        # to the same canonical form have already collapsed above via the
        # canonical_occs keying; surface_counts below only deduplicates and sorts.
        high_confidence_speakers: List[Dict[str, Any]] = []
        low_confidence_candidates: List[Dict[str, Any]] = []

        for name, occs in canonical_occs.items():
            count = len(occs)
            num_chapters = len(canonical_chapters[name])
            avg_quote_len = sum(len(o["quote"]) for o in occs) / max(count, 1)

            tag_counter = Counter(o["tag"] for o in occs)
            fav_tag = tag_counter.most_common(1)[0][0] if occs else "道"
            # Full lines, used only to derive habits below; not stored on the profile.
            full_quotes = [str(o.get("text", "")).strip() for o in occs if str(o.get("text", "")).strip()]

            speaker_profile = {
                "name": name,
                "occurrences": count,
                "chapters_count": num_chapters,
                "avg_dialogue_len": round(avg_quote_len, 1),
                "fav_tag": fav_tag,
                "common_tags": [tag for tag, _ in tag_counter.most_common(3)],
                "tone_type": self._classify_tone(full_quotes),
                "fixed_phrases": self._extract_fixed_phrases(full_quotes),
                "opening_words": self._count_opening_words(full_quotes),
                "sample_quotes": [o["quote"] for o in occs[:3]],
            }
            if alias_trace.get(name):
                speaker_profile["merged_aliases"] = sorted(alias_trace[name])

            # High confidence condition: >=3 occurrences AND across >= 2 chapters/chunks
            if count >= 3 and num_chapters >= 2:
                speaker_profile["confidence"] = "high"
                high_confidence_speakers.append(speaker_profile)
            else:
                speaker_profile["confidence"] = "low"
                low_confidence_candidates.append(speaker_profile)

        # Sort high confidence by occurrences descending
        high_confidence_speakers.sort(key=lambda x: x["occurrences"], reverse=True)
        low_confidence_candidates.sort(key=lambda x: x["occurrences"], reverse=True)

        # Calculate dao:shuo ratio
        # A tag ending in 道 (说道/问道/笑道...) belongs to the 道 family and is
        # counted once here. The previous version added the bare tag a second
        # time, doubling both sides and skewing the ratio whenever one family
        # was missing (the max(x, 1) guard then made it off by 2x).
        dao_count = sum(v for k, v in tag_counts.items() if k.endswith("道"))
        shuo_count = sum(v for k, v in tag_counts.items() if k.endswith("说"))
        dao_shuo_ratio = round(dao_count / max(shuo_count, 1), 2)

        # Tags used by exactly one identified speaker are a strong voiceprint
        # signal: they distinguish characters even when the tag pool is narrow.
        tag_to_speakers: Dict[str, Set[str]] = defaultdict(set)
        for profile in high_confidence_speakers:
            for tag in profile.get("common_tags", []):
                tag_to_speakers[tag].add(str(profile.get("name", "")))
        unique_tags: Dict[str, Dict[str, Any]] = {}
        for tag, speakers in tag_to_speakers.items():
            if len(speakers) == 1:
                owner = next(iter(speakers))
                unique_tags[tag] = {"speaker": owner, "count": int(tag_counts.get(tag, 0))}
        # Deterministic order: strongest evidence first, then tag name.
        unique_tags = dict(sorted(
            unique_tags.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:10])

        return {
            "total_quotes": len(raw_quotes),
            "dialogue_chars": dialogue_chars,
            "dialogue_ratio": round(dialogue_ratio, 4),
            "dialogue_ratio_pct": f"{dialogue_ratio * 100:.2f}%",
            "tag_frequencies": dict(tag_counts.most_common(15)),
            "dao_shuo_ratio": dao_shuo_ratio,
            "unique_tags": unique_tags,
            # 对话功能分布（信息交换/冲突对抗/情感表达/日常闲聊）。原始引语只在
            # 本方法内可见，这里只返回聚合分布，不落任何台词文本。
            "dialogue_functions": measure_dialogue_functions(raw_quotes),
            "high_confidence_speakers": high_confidence_speakers[:10],
            "low_confidence_candidates": [c["name"] for c in low_confidence_candidates[:20]],
        }
