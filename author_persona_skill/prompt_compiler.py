"""
作家分身提示词编译工具
将风格分析结果编译成可用的系统提示词
"""

from typing import Dict, Any, Optional


class PromptCompiler:
    """
    提示词编译器 - 将风格数据编译成实用的提示词
    """

    def __init__(self):
        self.scene_templates = {
            "battle": """
【战斗场景强化】
- 短句爆发率提升30%以上
- 动词密度提升，用动作性强的词
- 减少抒情，增加节奏感
- 感叹号可适当增加
""",
            "dialogue": """
【对话场景强化】
- 口语化功能词增加
- 省略号密度提升
- 对话为主，减少叙述
- 对话要符合角色性格
""",
            "scene": """
【场景描写强化】
- 增加环境细节
- 增强画面感
- 可适当使用长句铺陈
- 多用感官描写（视听嗅触）
""",
            "emotion": """
【情感场景强化】
- 增加心理描写
- 多用意象化表达
- 节奏可稍放缓
- 增加比喻和象征
""",
            "momentum": """
【气势场景强化】
- 多用排比和短句堆叠
- 节奏紧凑有力
- 增加气势描写
- 语气助词适当减少
""",
            "transition": """
【转场场景强化】
- 自然流畅的过渡
- 用动作或环境代替
- 避免生硬过渡词
- 保持整体节奏
"""
        }

    def compile_persona(
        self,
        author_name: str,
        quantitative_features: Optional[Dict] = None,
        qualitative_features: Optional[Dict] = None
    ) -> str:
        """
        编译作家分身提示词

        Args:
            author_name: 作家名称
            quantitative_features: 定量特征（可选）
            qualitative_features: 定性特征（可选）

        Returns:
            完整的系统提示词
        """
        prompt_parts = [
            f"【身份注入】你是作家{author_name}的文学分身。请严格遵循以下风格设定。"
        ]

        # 加入硬性统计约束
        if quantitative_features:
            prompt_parts.append(self._build_hard_constraints(quantitative_features))

        # 加入软性叙事约束
        if qualitative_features:
            prompt_parts.append(self._build_soft_constraints(qualitative_features))

        # 加入通用禁忌
        prompt_parts.append(self._build_taboo_section(qualitative_features))

        # 执行要求
        prompt_parts.append("【执行要求】现在，请完全按照上述风格回应创作任务。")

        return "\n\n".join(prompt_parts)

    def add_scene_enhancement(self, base_prompt: str, scene_type: str) -> str:
        """
        为提示词添加场景强化

        Args:
            base_prompt: 基础提示词
            scene_type: 场景类型

        Returns:
            强化后的提示词
        """
        if scene_type in self.scene_templates:
            return base_prompt + "\n\n" + self.scene_templates[scene_type]
        return base_prompt

    def _build_hard_constraints(self, features: Dict) -> str:
        """构建硬性统计约束部分"""
        sentence = features.get("sentence", {})
        vocab = features.get("vocabulary", {})
        punct = features.get("punctuation", {}).get("density_per_kilo", {})

        lines = ["【统计约束（硬性）】"]

        if "avg_length" in sentence:
            lines.append(f"- 平均句长：{sentence['avg_length']}字")
        if "short_rate" in sentence:
            lines.append(f"- 短句（<8字）比例：{sentence['short_rate']}%")
        if "long_rate" in sentence:
            lines.append(f"- 长句（>30字）比例：{sentence['long_rate']}%")
        if "ttr" in vocab:
            lines.append(f"- 词汇丰富度（TTR）：{vocab['ttr']}")
        if "function_word_ratio" in vocab:
            lines.append(f"- 功能词占比：{vocab['function_word_ratio']}")
        if "top_words" in vocab:
            lines.append(f"- 常用词：{'、'.join(vocab['top_words'][:8])}")

        main_puncts = [k for k, v in punct.items() if v > 5][:5]
        if main_puncts:
            lines.append(f"- 常用标点：{'、'.join(main_puncts)}")

        return "\n".join(lines)

    def _build_soft_constraints(self, features: Dict) -> str:
        """构建软性叙事约束部分"""
        lines = ["【叙事软约束】"]

        if "author_voice" in features:
            lines.append(f"- 文风特点：{features['author_voice']}")
        if "thinking_pattern" in features:
            lines.append(f"- 思维推进：{features['thinking_pattern']}")
        if "sentence_rhythm" in features:
            lines.append(f"- 句式节奏：{features['sentence_rhythm']}")
        if "emotional_arc" in features:
            lines.append(f"- 情感曲线：{features['emotional_arc']}")

        narrative = features.get("narrative_strategies", {})
        if isinstance(narrative, dict):
            if "opening" in narrative:
                lines.append(f"- 开头策略：{narrative['opening']}")
            if "transition" in narrative:
                lines.append(f"- 过渡策略：{narrative['transition']}")
            if "ending" in narrative:
                lines.append(f"- 结尾策略：{narrative['ending']}")

        rhetorics = features.get("rhetoric_devices", [])
        if isinstance(rhetorics, list) and rhetorics:
            names = [r.get("name", str(r)) for r in rhetorics[:3]]
            lines.append(f"- 常用修辞：{'、'.join(names)}")

        return "\n".join(lines)

    def _build_taboo_section(self, features: Optional[Dict]) -> str:
        """构建禁忌部分"""
        lines = ["【绝对禁忌】"]

        # 通用AI味禁忌
        generic = [
            "总而言之", "综上所述", "值得注意的是", "由此可见",
            "也就是说", "我们可以看到", "从这个角度来看",
            "需要指出的是", "值得一提的是", "必须承认的是"
        ]

        user_taboo = []
        if features and "taboo_phrases" in features:
            if isinstance(features["taboo_phrases"], list):
                user_taboo = features["taboo_phrases"]

        all_taboo = list(set(generic + user_taboo))
        lines.append(f"- 禁止使用：{'、'.join(all_taboo[:10])}")

        lines.append("- 禁止段落首句用连词（然而、此外等）")
        lines.append("- 禁止说教或总结性语句")
        lines.append("- 禁止过于规整的三段式结构")

        return "\n".join(lines)
