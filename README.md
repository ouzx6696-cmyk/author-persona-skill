# Author Persona Skill

> 把一部小说读成一份**可迁移的行文机制说明书**，并用实测数值把它钉死。

`author-persona-skill` 是一个面向中文小说语料的 AI 文风解构工具。它不模仿某位作者的词句，而是从语料中识别**稳定、可迁移的写作机制**——阅读效果从哪里来，句子、段落、对白、视角、标点、描写如何共同产生这种效果。

- **我负责什么**：对小说文本做深度文风解构，产出四层风格能力报告（脱敏人读 Markdown + 机器读 `report.json`），可另生成独立的作家分身系统提示词。
- **我不负责什么**：不为新故事设计剧情，不决定新项目的类型定位，不决定某一章该用哪张技法卡——那是下游 [novel-writer](https://github.com/ouzx6696-cmyk/novel-writer) 项目人格的职责。
- **我不复刻什么**：原作内容与专名。报告默认全脱敏，只保留行文机制。

## 四层报告

| 层 | 内容 | 真源 |
|---|---|---|
| 第〇部分 作家契约层 | 定位 / 写作目的与读者契约 / 风格标记综合 / 敌人条款 | `report.json` 的 `writer_contract` |
| 第一部分 定量风格分析 | 11 个小节，1.1–1.8 为实测指标，1.9–1.11 为定性分析 | 本地实测值 + 占位符注入 |
| 第二部分 技法调用卡 | 可执行的行文机制（句式 / 段落 / 标点 / 对话标签 / 视角调度） | `report.json` 机器块 |
| 第三部分 作家创作思维 | 6 个思维维度 + 题材适配边界 | `report.json` 的 `thinking_layer` |

四层之后另附三个附录（不改变四层标题，下游映射锚点不受影响）：附录 A 跨期对比矩阵（6 维实测演变量与趋势）、附录 B 定量扩展（低层测量层：可读性 / 词汇丰富度 / 句法复杂度 / 情感 / 词长词性 / 世界观五类 / 语义子维度 / 知识候选）、附录 C 分身配套产物（平台部署配置与三套风格模板摘要）。

输出为**脱敏人读 Markdown** 与**机器读 `report.json` sidecar**（`schema_version "6"`）。

## 三条核心机制

**数值保真。** 报告里的指标数值一律通过 `{{占位符}}` 引用本地实测值，模型禁止手写数字。渲染器统一替换，校验器审计全文——8 个核心指标（句长 / 段长 / 对话占比 / 短句率 / 长句率 / 比喻密度 / 逗句比 / 动作心理比）与实测冲突即拒绝，次要指标冲突仅记入 warnings。这一条把"LLM 编数字"这个最常见的失效模式从源头堵死。

**证据锚点防幻觉。** 引用的原文必须在对应 chunk 中规范化命中（空白 / 引号 / 破折号归一，最短 6 字、上限 80 字，超长直接拒绝）；未命中自动降级并标记；证据所属时期按语料实测重新推导。每条证据附一句"该句如何体现此技法"的注解。

**单一真源。** 第〇 / 二 / 三部分正文由 JSON 机器块渲染，Markdown 只输出标题行。手写这三部分的正文会被丢弃或拒绝。

## 三阶段工作流

```text
语料 .txt
  │
  ▼
[本地] prepare_analysis
  │   降噪 · 五时期分层采样 · 定量测算 · EID 证据库 · MID 注册表 · 占位符表
  │   产出 llm_prompt + llm_system_msg，以及交给 finalize 的 prepare_result
  ▼
[Agent] 调用 LLM  →  Markdown 正文 + 末尾 JSON 机器块
  │
  ▼
[本地] finalize_analysis
  │   解析 → 四重校验 + 渲染终检
  ├─ 通过   → 正式报告 + report.json（+ 保真附录 / 分身提示词）
  └─ 不通过 → *_rejected.md + repair_prompt（追加到同一会话重跑）
```

三个阶段各司其职：**prepare 只测量、不生成**；**LLM 只写内容、不写数值**；**finalize 只校验与渲染、不改写内容**。任何一环越界都会被对应的闸门拦下。

`prepare_analysis` 的返回值就是阶段间的交接单，`finalize_analysis` 开工前先验契约——字段缺失或版本过期会直接拒绝并给出缺失清单，而不是等到中途报 KeyError。

## 快速开始

需要 Python ≥ 3.10。分词依赖内嵌于 `libs/`（纯 Python jieba），无需外部安装；缺失时自动降级为正则近似并标注弱信号。

```bash
pip install -e .
```

或直接用 `PYTHONPATH=scripts`。

```bash
# 纯定量风格分析
python -m author_persona_skill analyze 小说.txt

# 章节索引与五时期阅读计划
python -m author_persona_skill plan 小说.txt --budget 150000

# Step 1：本地准备，产出 Prompt 与交接单
python -m author_persona_skill prepare 小说.txt --author 作者名 --title 作品名 \
    --output-prompt prompt.txt --output-json prep.json

# Step 2：由 Agent 把 prompt.txt 提交给 LLM，保存完整响应

# Step 3：解析、校验与渲染
python -m author_persona_skill finalize --prepare-json prep.json \
    --response-file response.txt --output-dir ./output [--trial-file 试写.txt]

# 独立保真校验
python -m author_persona_skill fidelity --trial 试写.txt \
    --report-json ./output/报告.json
```

也可用 Python API：

```python
from author_persona_skill import prepare_analysis, finalize_analysis

prepare_result = prepare_analysis(
    corpus_path="小说文件.txt",      # 或用 corpus_text 直接传纯文本
    author_name="来源作者名",        # 仅用于元信息登记与专名检测，不写进扮演身份
    work_title="作品标题",
    options={
        "desensitize": True,
        "generate_system_prompt": False,
        "allow_author_identity": False,
        "include_raw_evidence": False,
        "sample_budget_chars": 150000,
    },
)
```

## 保真闭环

报告完成后可以验证它：让模型按报告试写 2–3 个全新场景（每个 ≥800 字），覆盖日常互动、高压冲突、关键抉择三类，再用 `fidelity` 命令把试写的实测指标与报告的 `quantitative_features` 对照。

容差默认值之外，`prepare` 会从语料推导出**作者自然波动区间**（中位数 ± k·MAD）；试写值落在区间内即视为达标并标注 `basis: author_band`。类型标注可写在场景开头或 `# 场景N：冲突` 标题行，两种写法均生效。

## 脱敏

三层脱敏（L1 / L2 / L3）：

- 原作角色名全部原型化（如"果决探路主角型"）；
- 世界观术语全部意象类型化（如"高位圣山地标"）；
- 默认脱敏头只写 `WORK_xxxx` 伪名，真名仅在 `allow_author_identity` / `raw` 私有模式下出现。

报告主体严禁绑定原作者扮演式身份。规则细节见 `references/desensitization.md`。

## 与 novel-writer 协作（可选互操作）

本技能**独立运行**：给一份语料，产出四层报告与分身提示词，不依赖其他技能。若下游另有 [novel-writer](https://github.com/ouzx6696-cmyk/novel-writer) 这样的创作侧技能，可按下图衔接；两者各自独立，谁都不以对方为前提。

```text
author-persona-skill（能力理解）：语料 → 四层风格能力报告（观察与证据，留在项目外）
        ↓  可选：按 novel-writer 的 references/style_report_mapping.md 一次落位
novel-writer（故事创作）：报告能力 → state/author_persona.md 项目专属作家人格
        + state/story_bible.md 设定
        → 故事纲要、正文与连续性维护
```

本技能交付**观察与证据**，不替新故事做选择。采用、改写、舍弃哪些能力，由下游侧依据本书故事承诺在项目人格中裁决；不维护独立转接文件。报告原文始终保留在项目外。报告自身的四层结构与 `schema_version "6"` 自洽；下游映射表是否覆盖新增字段，属下游适配问题，不影响本技能产出与发布。

下游仓库（可选）：[novel-writer](https://github.com/ouzx6696-cmyk/novel-writer)

## 目录导览

| 路径 | 内容 |
|---|---|
| `SKILL.md` | 技能主文档：职责边界、阶段契约、核心铁律、三步工作流 |
| `manifest.yaml` | 平台清单：5 个函数的输入输出声明 |
| `scripts/author_persona_skill/` | 核心实现：corpus / analyzers / distill / report / fidelity / persona |
| `references/` | 5 份规范：报告 schema（含 schema 6 字段表）、质量基准（含新指标可靠性分级）、技法卡指南、脱敏规则、保真容差 |
| `libs/jieba/` | 内嵌分词库（纯 Python，含词典与 posseg），随包分发，无需外部安装 |
| `assets/templates/report_template_full.md` | 报告骨架（人读参照；运行时真源为 `report/renderer.py`） |
| `assets/examples/` | 玄幻与历史两类题材的完整报告范例（含附录 A/B/C） |
| `build_backend.py` | 无依赖的 PEP 517/660 构建后端 |

## 测试

```bash
python -m pytest tests/ -q
```

覆盖语料处理、定量分析、低层测量、话术建模、跨期矩阵、知识层、分身配套产物、内嵌依赖引导与降级、证据回验、脱敏、渲染、校验、保真与端到端管线。

## 授权

[MIT](LICENSE)
