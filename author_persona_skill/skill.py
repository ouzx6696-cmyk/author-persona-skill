"""
作家分身技能
用于Agent平台的简洁技能接口
"""

from typing import Dict, Any, Optional
from .style_analyzer import StyleAnalyzer
from .prompt_compiler import PromptCompiler


class AuthorPersonaSkill:
    """
    作家分身技能主类

    核心功能：
    1. analyze_style - 定量分析文本风格
    2. get_analysis_prompt - 获取LLM分析提示词
    3. compile_persona - 编译作家分身提示词
    """

    def __init__(self):
        self.analyzer = StyleAnalyzer()
        self.compiler = PromptCompiler()

    def analyze_style(self, text: str) -> Dict[str, Any]:
        """
        定量分析文本风格特征

        Args:
            text: 待分析的小说文本

        Returns:
            包含词汇、句式、标点、段落特征的字典
        """
        return self.analyzer.analyze(text)

    def get_analysis_prompt(self) -> str:
        """
        获取文学风格分析提示词模板

        Returns:
            提示词模板，用 {corpus} 替换成实际文本后可直接发给LLM
        """
        return self.analyzer.get_prompt_template()

    def compile_persona(
        self,
        author_name: str,
        quantitative_features: Optional[Dict] = None,
        qualitative_features: Optional[Dict] = None,
        scene_type: Optional[str] = None
    ) -> str:
        """
        编译作家分身提示词

        Args:
            author_name: 作家名称
            quantitative_features: 定量特征（来自analyze_style）
            qualitative_features: 定性特征（来自LLM分析）
            scene_type: 场景类型（可选）battle/dialogue/scene/emotion/momentum/transition

        Returns:
            完整的系统提示词，可直接作为LLM的system_prompt使用
        """
        prompt = self.compiler.compile_persona(
            author_name,
            quantitative_features,
            qualitative_features
        )

        if scene_type:
            prompt = self.compiler.add_scene_enhancement(prompt, scene_type)

        return prompt

    def quick_start(
        self,
        author_name: str,
        corpus_text: str,
        scene_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        一键生成：简单版（不依赖LLM）

        Args:
            author_name: 作家名称
            corpus_text: 小说文本
            scene_type: 场景类型（可选）

        Returns:
            包含quantitative_features和persona_prompt的字典
        """
        quant = self.analyze_style(corpus_text)
        persona = self.compile_persona(author_name, quant, scene_type=scene_type)

        return {
            "quantitative_features": quant,
            "persona_prompt": persona
        }
