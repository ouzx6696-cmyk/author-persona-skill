# 作家分身Skill

一个可以在各大Agent平台（Dify、Coze等）上安装使用的Skill，用于创建高保真的作家文学分身，实现专业级文风仿写。

## 功能特性

- 📚 **深度风格解构**：从小说语料中提取定量和定性的风格特征
- 🤖 **作家分身生成**：将风格指纹编译为LLM可用的提示词
- ⚙️ **多Agent协作**：编剧、风格裁判、润色Agent协同工作
- 🎯 **迭代优化**：多轮迭代确保生成文本高度贴合目标风格
- 🔌 **跨平台兼容**：支持Dify、Coze等主流Agent平台

## 快速开始

### 1. 基础使用

```python
from author_persona_skill import AuthorPersonaSkill

# 创建Skill实例
skill = AuthorPersonaSkill()

# 分析小说语料
result = skill.analyze_style(
    corpus_text="你的小说语料...",
    author_name="作家名称"
)

# 获取风格指纹
style_profile = result["style_profile"]

# 编译分身提示词
compile_result = skill.compile_persona(style_profile, "作家名称")
persona_prompt = compile_result["persona_prompt"]

# 生成分身文本
generate_result = skill.generate_with_persona(
    persona_prompt=persona_prompt,
    user_request="你的创作需求"
)
```

### 2. 在Dify平台使用

1. 在Dify中创建新的Plugin
2. 复制 `platforms/dify_adapter.py` 中的配置
3. 配置环境变量 `OPENAI_API_KEY`（可选）
4. 开始使用！

```python
from author_persona_skill.platforms import DifySkillAdapter

adapter = DifySkillAdapter(llm_client=your_llm_client)

# 调用完整工作流
result = adapter.run({
    "action": "complete_workflow",
    "corpus_text": "你的小说语料...",
    "author_name": "作家名称",
    "user_request": "创作需求"
})
```

### 3. 在Coze平台使用

```python
from author_persona_skill.platforms import CozeSkillAdapter

adapter = CozeSkillAdapter(llm_client=your_llm_client)

# 调用完整工作流
result = adapter.handle_plugin_call({
    "method": "complete_workflow",
    "parameters": {
        "corpus_text": "你的小说语料...",
        "author_name": "作家名称",
        "user_request": "创作需求"
    }
})
```

## Skill功能说明

### 主要函数

| 函数名 | 说明 |
|--------|------|
| `analyze_style` | 分析小说文本，提取风格指纹 |
| `compile_persona` | 将风格指纹编译为分身提示词 |
| `generate_with_persona` | 使用作家分身进行文本生成 |
| `complete_workflow` | 完整工作流：从语料到生成一站式处理 |

### 支持的场景类型

- `battle`：战斗场景
- `dialogue`：对话场景
- `scene`：场景描写
- `emotion`：情感描写
- `momentum`：气势描写
- `transition`：转场描写

## 平台支持

### Dify平台

- 支持Provider集成方式
- 支持4个主要工具函数
- 配置文件见 `platforms/dify_adapter.py`

### Coze平台

- 支持Plugin集成方式
- 配置文件见 `platforms/coze_adapter.py`

### 自定义平台

使用统一API接口，轻松适配其他平台：

```python
from author_persona_skill.api import create_api

api = create_api(llm_client=your_llm_client)

result = api.handle_request({
    "action": "complete_workflow",
    "params": {...}
})
```

## 配置说明

### 环境变量

```env
# OpenAI API配置
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4

# DeepSeek API配置
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### LLM集成

```python
from author_persona_skill import AuthorPersonaSkill
from llm_integration import LLMClient

# 创建LLM客户端
llm_client = LLMClient(provider="openai")

# 创建带LLM的Skill实例
skill = AuthorPersonaSkill(llm_client=llm_client)
```

## 目录结构

```
author_persona_skill/
├── __init__.py                 # 包入口
├── skill_main.py              # 核心Skill实现
├── api.py                     # 统一API接口
├── manifest.yml               # Skill配置文件
├── README_SKILL.md            # 本文档
├── platforms/                 # 平台适配器
│   ├── __init__.py
│   ├── dify_adapter.py       # Dify平台适配器
│   └── coze_adapter.py       # Coze平台适配器
└── examples/                  # 示例代码
    ├── __init__.py
    └── quick_start.py         # 快速开始示例
```

## 使用示例

### 示例1：分析风格

```python
result = skill.analyze_style(
    corpus_text="夜色如墨，月光透过...",
    author_name="金庸"
)
```

### 示例2：一键生成

```python
result = skill.complete_workflow(
    corpus_text="你的小说语料...",
    author_name="作家名称",
    user_request="写一段古城相遇的场景"
)
```

### 示例3：迭代优化

```python
result = skill.generate_with_persona(
    persona_prompt=persona_prompt,
    user_request="创作需求",
    style_profile=style_profile,
    enable_iteration=True,
    max_iterations=3
)
```

## 常见问题

### Q: 需要配置LLM才能使用吗？
A: 不需要。基础功能（风格分析、提示词编译）可以在无LLM的情况下使用。完整功能（迭代优化、自动生成）需要配置LLM。

### Q: 支持哪些LLM？
A: 支持OpenAI、DeepSeek，以及任何兼容OpenAI格式的API。

### Q: 语料需要多少字？
A: 建议至少1000字以上，效果更好。

### Q: 可以在商业项目中使用吗？
A: 可以，遵循MIT许可证。

## 开发说明

### 扩展新平台

在 `platforms/` 目录下添加新的适配器文件：

```python
# platforms/new_platform_adapter.py
class NewPlatformAdapter:
    def __init__(self, llm_client=None):
        self.api = create_api(llm_client)
        
    def handle_call(self, request):
        # 处理平台请求
        pass
```

## 许可证

MIT License

## 联系方式

如有问题或建议，欢迎提出Issue！
