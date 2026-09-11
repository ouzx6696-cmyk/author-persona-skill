---
name: author-persona-skill
description: 当需要解构小说文风、提取写作技法、生成风格能力报告或制作作家分身系统提示词时使用——用户提到文风分析、文笔诊断、语言风格量化、模仿某位作者的写法时即应触发，无需点名本技能。产出四层报告（第〇部分 作家契约层/定量层/技法调用卡层/思维层，第〇部分由 JSON 的 writer_contract 单一真源渲染）：指标数值一律经占位符注入本地实测值，核心指标与实测冲突即拒绝；技法卡须通过行文机制闸门并逐条证据回验；报告默认全脱敏，只模仿行文机制、不复刻原作内容与专名。输出脱敏人读 Markdown 与机器读 report.json（schema_version "5"），可经 novel-writer 按转译映射表一次落位为项目人格与设定。本技能只负责理解与报告，不负责新故事的剧情设计、类型定位与技法调用决策。面向中文小说语料，纯标准库实现。
metadata:
  version: "10.2.0"
  author: 专家级作者系统团队
  category: 内容创作
---

# 作家分身技能 (Author Persona Skill) v10.2.0

> 一句话：把一部小说读成一份**可迁移的行文机制说明书**，并用实测数值把它钉死。

> 本技能注册名为 `author-persona-skill`，代码包与目录名为 `author_persona_skill`，同指本技能；报告 schema（`schema_version "5"`）自 10.0.0 起保持稳定。

## 我负责什么

对小说文本做深度文风解构，从语料中识别**稳定、可迁移的写作机制**——阅读效果从哪里来，句子、段落、对白、视角、标点、描写如何共同产生这种效果，哪些是作者能力、哪些只是题材内容或原作专名。

## 我不负责什么

- 不为新故事设计剧情，不决定新项目的类型定位；
- 不决定某一章应该使用哪张技法卡（那是 `novel-writer` 项目人格的职责）；
- 不把定量指标变成写作硬阈值——指标只描述实测事实与趋势；
- 不复刻原作内容与专名——报告默认全脱敏，只保留行文机制。

## 最终输出

符合 `novel-writer` 契约的四层风格能力报告：脱敏人读 Markdown + 机器读 `report.json` sidecar（`schema_version "5"`）。四层为：第〇部分 作家定义与读者契约（作家契约层）/ 第一部分 定量风格分析 / 第二部分 核心写作技法（技法调用卡）/ 第三部分 作家创作思维与宏观心智。可另生成独立的作家分身系统提示词。全程仅依赖 Python 标准库。

## 什么时候用我

用户提到文风分析、文笔诊断、语言风格量化、想模仿某位作者的写法时触发。典型入口是 `novel-writer` 新项目的第一步：先理解一种写法，再做能力落位（见文末「与 novel-writer 的协作关系」）。

---

## 🗺️ 全流程一图

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

三个阶段各司其职：**prepare 只测量、不生成**；**LLM 只写内容、不写数值**（数值用占位符）；**finalize 只校验与渲染、不改写内容**。任何一环越界都会被对应的闸门拦下。

## 📐 阶段契约（prepare → finalize 的交接单）

`prepare_analysis` 的返回值就是交接单，`finalize_analysis` 开工前先验契约（`contracts.py`），字段缺失或版本过期会**直接拒绝并给出缺失清单**，而不是等到中途报 KeyError。

| 类别 | 键 | 作用 |
|---|---|---|
| 必返 | `llm_prompt` / `llm_system_msg` | 交给 Agent 调 LLM 的两条消息 |
| 必返 | `evidence_store` / `evidence_store_ids` | 原文证据库（EID → 文本/时期/偏移），供回验 |
| 必返 | `era_map` / `era_spans` | 五时期归属与区间（开头/发展/成熟/演变/结尾） |
| 必返 | `quantitative_features` | 定量实测值（报告 1.x 节的唯一数值来源） |
| 必返 | `metric_registry` / `placeholder_map` | MID 注册表与 `{{占位符}}` 映射 |
| 必返 | `proper_noun_candidates` | 脱敏候选池（只映射池内条目） |
| 必返 | `prepare_meta` | 采样区间、噪音比、开关快照、`prepare_schema_version` |
| 选返 | `era_excerpts` / `era_ranges` / `era_id_map` | 跨期对照原文与时期索引 |
| 选返 | `era_window_metrics` | 每时期窗口指标 → 保真闭环的动态容差带 |
| 选返 | `chunk_offsets` / `evidence_pool` | 偏移索引与候选证据池 |

契约版本为 `prepare_schema_version: "1"`；手工拼装 `prepare_result` 时用 `describe_prepare_contract()` 查最新字段表，用 `validate_prepare_result(prep)` 先自检。

## 🚨 核心铁律

> 面向分析 LLM 的完整执行铁律（9 条）见 `scripts/author_persona_skill/report/templates.py` 的 MASTER_SYSTEM_PROMPT；此处 7 条为 skill 级使用约束，两者角色不同。

1. **模仿风格，而非复刻内容**
   - 报告主体严禁绑定原作者扮演式身份（如“你就是原作者本人”）；默认脱敏头仅写 `WORK_xxxx` 伪名，真名仅 `allow_author_identity/raw` 私有模式出现。
   - 原作角色名全部原型化（如"果决探路主角型"）；世界观术语全部意象类型化（如"高位圣山地标"）。
2. **数值保真**：第一部分指标数值一律通过 `{{占位符}}` 引用实测值，禁止手写指标数值。渲染器统一替换，校验器审计全文——8 个核心指标（句长/段长/对话占比/短句率/长句率/比喻密度/逗句比/动作心理比）与实测冲突即拒绝；次要指标冲突仅记入 warnings。
3. **材料边界**：只允许基于 Prompt 提供的定量指标、五时期锚点池与代表片段归纳，禁止调用模型对该作品的记忆补充论据（第〇部分 writer_contract 同受此约束，无法合成时显式写「报告未提供」）。短语料会自动缩减时期数量（1–5 个）；fallback 虚拟分段下跨期证据门禁不适用；启发式与弱信号指标须按数据源可靠性降级表述。
4. **技法必须是行文机制**：技法卡描述句式/段落/标点/对话标签/描写配比/视角调度层面的可执行规则；情节梗概或题材设定冒充技法会被内容闸门直接拒绝。每张卡必填 `serves_purpose`（本卡服务的阅读效果）。
5. **诊断深度优先**：每个小节是"命名型总起句 + 因果诊断段"（数值并列→共振/矛盾→机制命名→阅读效果），禁止只堆数字。质量基准见 `references/quality-baseline.md`。
6. **证据锚点防幻觉**：引用的原文必须在对应 chunk 中规范化命中（空白/引号/破折号归一；最短 6 字，上限 80 字，超长直接拒绝），未命中自动降级并标记；证据所属时期一律按语料实测重推导；每条证据附一句"该句如何体现此技法"的注解。
7. **单一真源**：第〇/二/三部分正文由 JSON 机器块渲染，Markdown 只输出标题行；手写这三部分的正文会被丢弃或拒绝。

## ⚡ 标准三步工作流

### Step 1：prepare_analysis（本地计算，无需 LLM）

```python
from author_persona_skill import prepare_analysis

prepare_result = prepare_analysis(
    corpus_path="小说文件.txt",      # 或用 corpus_text 直接传纯文本
    author_name="来源作者名",        # 仅用于元信息登记与专名检测，不写入扮演身份
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

Step 2 只需要两个返回字段：
- `prepare_result["llm_prompt"]`：完整用户 Prompt（内含定量指标、数值占位符注册表、五时期锚点池、代表片段摘录与输出规范）。
- `prepare_result["llm_system_msg"]`：System 消息。

### Step 2：调用 LLM（由 Agent 执行）

提交 System 与 User Prompt 后，Agent 撰写报告时遵守：

1. **先深读再动笔**：通读 Prompt 中的质量基准、五时期代表片段与锚点池，跨期对比是归纳的前提。
2. **第〇部分只写标题行**：作家契约（positioning / purpose / style_marks_synthesis / enemy_clauses 四字段，enemy_clauses 2–4 条）全部写入 JSON 的 `writer_contract`，只能从本次语料合成，禁止调用模型记忆；Markdown 里只输出"## 第〇部分：作家定义与读者契约（作家契约层）"标题行。
3. **第一部分只写诊断**：11 个小节按"命名型总起句 + 因果诊断段"展开，1.1–1.8 节指标数值一律用占位符（如 `平均句长 {{avg_sent_len}} 字`），1.9–1.11 为定性小节。
4. **第二部分只写机制**：技法卡内容全部写入 JSON 机器块（名称、定义、步骤落在行文层；`serves_purpose` 必填；失效边界写齐"禁用场景+退化成因+规避动作"；`evidence[].metric` 必须标注指标名并附注解）；Markdown 里只输出第二部分标题行，正文由 JSON 渲染；至少一张卡给出跨时期双锚点证据（按卡校验）。
5. **第三部分只写 JSON**：6 个思维维度 + 题材适配边界全部写入 `thinking_layer`（Markdown 只输出标题行）；长线布局须引用 ≥2 组不同时期锚点（写成 `[c001]` 锚点 ID 形式，校验器按此统计跨期性）。
6. **末尾附 JSON 数据块**：`desensitization_map` 只映射候选池实际给出的条目（通常 ≤10 项），替换标签用 2–4 字中性原型词；候选池之外的额外键仅记入 `validation.warnings`（不阻断，见 `references/desensitization.md`）。

LLM 完整响应（Markdown 正文 + ```json 块）原样保留，交给 Step 3。

### Step 3：finalize_analysis（本地解析、校验与渲染）

```python
from author_persona_skill import finalize_analysis

result = finalize_analysis(
    prepare_result=prepare_result,
    llm_response=llm_response_text,     # Step 2 的完整响应
    output_dir="./output",
    base_name="作品_风格解构报告",
    trial_text=None,                    # 可选：试写文本，触发保真闭环并写入报告附录
)
```

#### 四重校验 + 渲染终检（全部为阻断级）

| 校验 | 内容 | 失败后果 |
|---|---|---|
| 结构体检 | 四段标题齐全（第〇/一/二/三）、JSON 块存在、正文长度达标 | 拒绝 |
| Schema+证据 | writer_contract 四字段、技法卡字段/数量/内容闸门（含 serves_purpose）、思维层七维、引文规范化回验（6–80 字）、跨期证据按卡校验（era 按语料实测重推导） | 拒绝 |
| 脱敏反向校验 | 候选专名在非引文正文中零泄漏 | 拒绝 |
| 数值审计 | 8 核心指标 vs 实测值比对（prose 与 JSON 字段同审）；次要指标仅警告 | 拒绝（核心冲突） |
| 渲染终检 | 对渲染后的公开产物（meta 等渲染层字段）再做身份泄漏扫描 | 拒绝并删除已落盘产物（含 manifest） |

#### 校验分层：什么阻断、什么只提示

| 层 | 字段 | 是否阻断 | 含义 |
|---|---|---|---|
| 错误 | `validation.errors` | **是** | 四重校验/终检未过，不生成正式报告 |
| 提示 | `validation.warnings` | 否 | 脱敏覆盖缺口等非阻断事项，供回读 |
| 质量自评 | `validation.quality` / `quality_status` / `publishable` | 否 | 诊断深度、长线布局锚点、风格标记数据支撑率的事后自评 |
| 保真自评 | `result["fidelity"]` | 否（但影响顶层 `status`） | 试写文本 vs 基线指标的闭环结果 |

#### 修复回路（校验失败后怎么重跑）

校验失败时 `finalize_analysis` **不会**让你猜原因——除了 `rejected_path` 与 `errors`，还返回一份 `repair_prompt`：

- 返回值：`result["repair_prompt"]`（同时挂在 `validation.repair_prompt`）；
- CLI：`--repair-prompt-out 修复.txt` 直接落盘，stdout 会提示路径；
- 内容：错误清单 + 每类错误的修法 + 可引用证据菜单（EID/片段/时期，标注 UNTRUSTED DATA）+ 专名候选池 + 输出契约速查。

**用法：把这份提示词追加到同一条会话里重试**，LLM 带着"哪里错了、怎么改"再写一遍，而不是从头重新生成。拿到新响应后重跑 `finalize_analysis` 即可（`prepare_result` 无需重算）。

#### 失败模式的三种含义（不要混为一谈）

- **校验失败（阻断）**：不生成正式报告，仅落盘 `xxx_风格解构报告_rejected.md`（`result["rejected_path"]`），`validation.errors` 列出全部原因。**必须修复后重跑**。
- **fidelity 未达标（自评）**：保真闭环独立于校验，不拒绝渲染——报告照常落盘、偏差表写入附录、顶层 `status` 置为 `failed`；是否返工由调用方决定。
- **质量自评未达标（自评）**：可能出现「`status: passed` 而 `publishable: failed`」（契约合规但深度未达生产基准），是否返工由调用方决定。

决策表：

| 看到什么 | 报告落盘了吗 | 下一步 |
|---|---|---|
| `validation.status: failed` | 否（只有 `_rejected.md`） | 用 `repair_prompt` 重试，或修 prompt 后重跑 |
| `validation.status: passed` + `fidelity.status: failed` | 是（附录含偏差表） | 报告可用；如需达标，改试写文本后用 `fidelity` 子命令单独复核 |
| `status: passed` + `publishable: failed` | 是 | 报告合规，深度不足；按 `quality.notes` 补写后重跑 |

#### 产出物

- `report_path` / `report_json_path`：正式 Markdown 与机器读 sidecar（`passed` 时）；第〇/二/三部分由 JSON 单一真源渲染，sidecar 的 `schema_version` 为 `"5"`，携带 `provenance`、`validation_summary`（含 `quality` 质量自评）、`fidelity` 与 `artifact_policy`。
- `desensitization_map_path` / `manifest_path`：按报告名作用域落盘的 `{base_name}_desensitization_map.json` 与 `{base_name}_manifest.json`（同目录多次 finalize 互不覆盖；映射表仅含中性标签，原键映射只进私有 sidecar）。
- `fidelity`：传入 `trial_text` 时的保真闭环结果（同时写入报告附录）。
- `system_prompt`：`generate_system_prompt=True` 时生成的分身系统提示词（含实测数值铁律与合成正反示范）。
- `status`：`"passed"` 或 `"failed"`。

## 💻 CLI

`python -m` 需先 `pip install -e .`（或 `PYTHONPATH=scripts`）；安装后亦可用 `author-persona-skill` 直接调用。参数细节见各命令 `--help`。

```bash
python -m author_persona_skill analyze 小说.txt [--json]          # 纯定量风格分析
python -m author_persona_skill plan 小说.txt --budget 150000      # 章节索引与五时期阅读计划
python -m author_persona_skill prepare 小说.txt --author 作者名 --title 作品名 --budget 150000 \
    --output-prompt prompt.txt --output-json prep.json            # Step 1
python -m author_persona_skill finalize --prepare-json prep.json --response-file response.txt \
    --output-dir ./output [--base-name 报告名] [--trial-file 试写.txt] \
    [--repair-prompt-out 修复.txt]                                 # Step 3；校验失败生成 *_rejected.md
python -m author_persona_skill fidelity --trial 试写.txt --report-json ./output/报告.json  # 独立保真校验
```

## 🧪 保真闭环

试写用单独一行 `---`（或 `===`）分隔场景，须为 2–3 个全新场景、每个 ≥800 字，覆盖日常互动（常态呼吸）、高压冲突（短句脉冲与动作心理比）、关键抉择（思维层复现）；类型标注可写在场景开头或 `# 场景N：冲突` 标题分隔行（两种写法均生效），标注类型（日常/冲突/抉择）时三类必须齐全。场景强制与复制检测在 finalize 与独立调用两条路径中同源（`run_fidelity_check` 单点执行，以报告 `quantitative_features` 为基准；无参照文本时复制检测跳过并如实提示）。容差默认值之外，prepare 产出的 `era_window_metrics` 会推导出**作者自然波动区间**（中位数 ± k·MAD），试写值落在区间内即视为达标并标注 `basis: author_band`。详见 `references/fidelity.md`。

## 🔗 与 novel-writer 的协作关系

两个技能构成一套创作系统的先后两环：

```text
本技能（能力理解）：语料 → 四层风格能力报告（观察与证据，留在项目外）
        ↓  由虚拟作家人工通读，按 novel-writer 的 references/style_report_mapping.md 一次落位
novel-writer（故事创作）：报告能力 → state/author_persona.md 项目专属作家人格（日常唯一人格输入）
        + state/story_bible.md 设定
        → 故事纲要、正文与连续性维护
```

职责边界：

- 本技能交付**观察与证据**，不替新故事做选择——采用、改写、舍弃哪些能力，由 `novel-writer` 侧依据本书故事承诺在项目人格中裁决；**不维护独立转接文件**，落位结果直接写进 `author_persona.md` 与 `story_bible.md`；
- 转译由 `novel-writer` 的虚拟作家人工完成，逐项按 `references/style_report_mapping.md` 的映射表落位；报告路径登记在项目 `state/memory.md` 的「五、风格报告」（两技能同仓时按相对路径引用，跨仓使用时以目标项目版本为准），本技能不参与项目人格生成与技法调用决策；
- 报告原文始终保留在项目外；`novel-writer` 的转译映射表只覆盖现行四层报告（`schema_version "5"`，10.0.0 起），更早的非四层报告不在其覆盖范围内。

衔接示例：

```bash
# 1) 本技能产报告，报告原文留在项目外
python -m author_persona_skill prepare 小说.txt --author 作者名 --title 作品名 --output-json prep.json
# ... finalize 产出 ./output/作品_风格解构报告.md
# 2) novel-writer 建项目；报告路径由虚拟作家登记进 state/memory.md「五、风格报告」，
#    再按 references/style_report_mapping.md 一次落位进 author_persona.md 与 story_bible.md
python novel-writer/scripts/init_project.py /path/to/my_novel
```

## 📚 目录导览

- `references/report-schema.md`：四层契约字段规范（含占位符契约与 writer_contract 契约）
- `references/quality-baseline.md`：报告质量基准（因果诊断/失效边界/跨期证据/量化禁令，验收参照系）
- `references/technique-card-guide.md`：技法卡编写指南（好卡/坏卡对照）
- `references/desensitization.md`：三层脱敏与反向校验规则（指 L1/L2/L3 脱敏层，非报告层数）
- `references/fidelity.md`：保真闭环容差表与动态波动区间
- `assets/templates/report_template_full.md`：报告骨架（人读参照；运行时真源为 `scripts/author_persona_skill/report/renderer.py`）
- `assets/examples/xuanhuan_style_report.md`、`assets/examples/historical_style_report.md`：两类题材的报告范例
