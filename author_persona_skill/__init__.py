"""
作家分身技能 - 主入口模块
用于Agent平台的简洁工具接口
"""

from .skill import AuthorPersonaSkill
from .style_analyzer import StyleAnalyzer
from .prompt_compiler import PromptCompiler

__version__ = "2.0.0"
__all__ = ["AuthorPersonaSkill", "StyleAnalyzer", "PromptCompiler"]
