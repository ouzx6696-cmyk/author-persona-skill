# 作家分身技能

为Agent平台提供的简洁实用的风格工具集。**不自己搞一套复杂Agent系统**，而是提供工具让平台的AI智能体来调用！

## 核心功能

1. **定量风格分析** - 本地计算文本的词汇、句式、标点、段落特征
2. **LLM分析提示词** - 获取文学风格分析提示词模板
3. **提示词编译** - 将分析结果编译成作家分身提示词

## 快速使用

### 在Agent平台（Solo/Dify/Coze等）

直接使用 `author_persona_skill` 目录作为技能包上传！

### 本地测试

```python
from author_persona_skill import AuthorPersonaSkill

skill = AuthorPersonaSkill()

# 1. 定量分析风格
features = skill.analyze_style("你的小说文本...")

# 2. 获取分析提示词模板
prompt = skill.get_analysis_prompt()  # 用你的文本替换 {corpus}

# 3. 编译作家分身提示词
persona = skill.compile_persona(
    author_name="作家名",
    quantitative_features=features,
    qualitative_features=...  # 可从LLM获取
)
```

## 项目结构

```
author_persona_skill/
├── __init__.py          # 主入口
├── skill.py             # 主Skill类
├── style_analyzer.py    # 风格分析器
├── prompt_compiler.py   # 提示词编译器
└── SKILL.md            # 技能描述
```

## 在Agent平台的典型使用流程

```
用户上传小说文本
  ↓
调用 analyze_style() 获取定量特征
  ↓
调用 get_analysis_prompt() + 替换文本，发给LLM做定性分析
  ↓
调用 compile_persona() 编译成作家分身提示词
  ↓
Agent平台用这个提示词作为system_prompt来创作！
```
