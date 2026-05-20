"""
作家风格分析工具
提供定量风格分析和定性分析提示词
"""

import re
import jieba
import numpy as np
from collections import Counter
from typing import Dict, Any


class StyleAnalyzer:
    """
    风格分析器 - 只做一件事：分析文本风格特征
    """

    def __init__(self):
        self.chinese_func_words = [
            "的", "了", "在", "是", "有", "和", "就", "都", "而", "及",
            "与", "之", "或", "但", "然而", "因此", "所以", "却", "也",
            "忽然", "突然", "缓缓", "慢慢", "轻轻", "渐渐", "终于", "最终"
        ]

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        分析文本风格特征

        Args:
            text: 待分析的文本

        Returns:
            风格特征字典
        """
        if not text or len(text.strip()) < 50:
            raise ValueError("请提供至少50字以上的文本")

        # 分词和分句
        sentences = self._split_sentences(text)
        words = list(jieba.cut(text))
        word_counts = Counter(words)
        total_words = len(words)
        unique_words = len(word_counts)

        # 1. 词汇层分析
        func_word_count = sum(word_counts.get(w, 0) for w in self.chinese_func_words)
        ttr = unique_words / max(total_words, 1)
        top_words = [w for w, c in word_counts.most_common(20) if len(w.strip()) > 0]

        # 2. 句法层分析
        sentence_lengths = [len(s) for s in sentences]
        avg_sentence_len = np.mean(sentence_lengths) if sentence_lengths else 0
        short_count = sum(1 for l in sentence_lengths if l < 8)
        long_count = sum(1 for l in sentence_lengths if l > 30)
        short_rate = short_count / max(len(sentences), 1) * 100
        long_rate = long_count / max(len(sentences), 1) * 100

        # 3. 标点分析
        punct_counts = self._count_punctuation(text)
        total_chars = len(text)
        punct_density = {
            k: (v / max(total_chars, 1)) * 1000
            for k, v in punct_counts.items()
        }

        # 4. 段落分析
        paragraphs = [p for p in text.split('\n') if p.strip()]
        avg_paragraph_len = np.mean([len(p) for p in paragraphs]) if paragraphs else 0
        dialogue_count = self._count_dialogue(text)

        return {
            "vocabulary": {
                "total_words": total_words,
                "unique_words": unique_words,
                "ttr": round(ttr, 3),
                "function_word_ratio": round(func_word_count / max(total_words, 1), 3),
                "top_words": top_words[:10]
            },
            "sentence": {
                "total_sentences": len(sentences),
                "avg_length": round(avg_sentence_len, 1),
                "short_rate": round(short_rate, 1),
                "long_rate": round(long_rate, 1)
            },
            "punctuation": {
                "counts": punct_counts,
                "density_per_kilo": {k: round(v, 1) for k, v in punct_density.items()}
            },
            "paragraph": {
                "total_paragraphs": len(paragraphs),
                "avg_length": round(avg_paragraph_len, 1),
                "dialogue_count": dialogue_count
            }
        }

    def get_prompt_template(self) -> str:
        """
        获取文学风格分析提示词模板（用于LLM）

        Returns:
            提示词模板，需要用 {corpus} 替换成实际文本
        """
        return """你是一位资深文学风格分析师。请仔细阅读以下小说片段，从这8个维度分析作家的独特风格，以JSON格式返回：

文本：
{corpus}

分析维度：
1. author_voice: 用一句话概括作者的文风特征
2. thinking_pattern: 思维推进方式（如线性叙事、跳跃拼贴、意识流等）
3. sentence_rhythm: 句式节奏特征（长句铺陈/短句爆发/长短交替等）
4. lexical_fingerprint: 列出至少8个标志性高频词或短语
5. rhetoric_devices: 最常用的3-5种修辞手法，每种带一个简短例子
6. narrative_strategies: 包含opening（开头方式）、transition（过渡方式）、ending（结尾方式）三个子字段
7. emotional_arc: 常见情感变化轨迹（如"平静→冲突→升华"）
8. taboo_phrases: AI味短语黑名单（至少3个，如"总而言之"这种）

返回JSON格式，不要加其他内容：
{
  "author_voice": "冷峻精准，擅长细节刻画",
  "thinking_pattern": "线性叙事，层层递进",
  "sentence_rhythm": "短句爆发为主",
  "lexical_fingerprint": ["词1", "词2", "词3", "词4", "词5", "词6", "词7", "词8"],
  "rhetoric_devices": [
    {"name": "比喻", "example": "像生锈的齿轮"},
    {"name": "拟人", "example": "风在低语"}
  ],
  "narrative_strategies": {
    "opening": "从环境切入",
    "transition": "用动作代替",
    "ending": "留白式结尾"
  },
  "emotional_arc": "平静→冲突→升华",
  "taboo_phrases": ["总而言之", "综上所述", "值得注意的是"]
}
"""

    def _split_sentences(self, text: str) -> list:
        separators = r'[。！？!?]'
        sentences = re.split(separators, text)
        return [s.strip() for s in sentences if s.strip()]

    def _count_punctuation(self, text: str) -> Dict[str, int]:
        pattern = r'[，。！？；：""''（）【】《》、—…!?;:""\'\'()\[\]<>]'
        puncts = re.findall(pattern, text)
        return dict(Counter(puncts))

    def _count_dialogue(self, text: str) -> int:
        dialogue_pattern = r'["“][^"”]*["”]'
        dialogues = re.findall(dialogue_pattern, text)
        return len(dialogues)
