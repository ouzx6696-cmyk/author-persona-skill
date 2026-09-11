# 风格能力报告字段与契约规范

风格能力报告由**人读 Markdown 报告**与**机器读 JSON sidecar (`report.json`)** 双通道组成。自 10.0.0 起报告为四层：第〇部分（作家契约层，`writer_contract`）+ 三部分；`report.json` 的 `schema_version` 为 `"5"`。

报告头部的「报告版本」由渲染器按包版本自动注入（`v10.2.0 (四层契约 · 脱敏 · 证据锚点 · 保真闭环)`）；范例中的版本行仅为最终产物形态示意。

---

## 0. 数值占位符契约（第一部分强制）

第一部分 1.1–1.8 节的所有数值必须通过 `{{占位符}}` 引用 `prepare` 实测值，禁止手写数字：

| 占位符（示例） | 含义 |
|---|---|
| `{{avg_sent_len}}` / `{{median_sent_len}}` | 平均/中位句长 |
| `{{short_sent_ratio_pct}}` / `{{long_sent_ratio_pct}}` | 短句率 / 长句率 |
| `{{avg_para_len}}` / `{{short_para_ratio_pct}}` | 平均段长 / 极短段率 |
| `{{dialogue_ratio_pct}}` / `{{dao_shuo_ratio}}` | 对话占比 / 道:说比 |
| `{{punc_ellipsis}}` / `{{punc_dash}}` 等千字密度 | 标点密度 |
| `{{metaphor_density}}` 等修辞密度 | 修辞指标 |
| `{{third_person_count}}` / `{{first_person_count}}` | 人称代词计数 |
| `{{action_count}}` / `{{mental_count}}` / `{{env_count}}` | 描写主导句计数 |

完整注册表由 `llm_prompt` 中的"数值占位符注册表"给出。渲染时统一替换为实测值；
校验器随后审计全文：**8 个核心指标**（平均句长/段长、对话占比、短句率/长句率、比喻密度、逗句比、动作心理比）
与实测冲突将拒绝整份报告；其余次要指标冲突仅降级为 `validation.warnings` 提示。

---


## 0.5 第〇部分：作家定义与读者契约（作家契约层，10.0.0 新增）

Markdown 里只输出「## 第〇部分：作家定义与读者契约（作家契约层）」标题行，正文由 JSON 的 `writer_contract` 单一真源渲染为 〇.1–〇.4 小节。四字段均必填：非空（≥5 字）或显式写「报告未提供」，禁止编造：

```json
{
  "writer_contract": {
    "positioning": "题材系别 + 平台语境的一句话定位",
    "purpose": "作者与读者的体验契约：读者每章最低得到什么",
    "style_marks_synthesis": "由 1.11 风格标记综合出的整体风格命题",
    "enemy_clauses": ["敌人条款 2-4 条：从低密度/负向指标反推的禁写项"]
  }
}
```

- 内容只能从本次语料的定量数据与证据合成（铁律 3 材料边界的延伸），禁止调用模型记忆补写。
- 缺失 `writer_contract` 或字段为空将使整份报告被拒绝（fail-closed，与第二/三部分同规格）。
- 下游 novel-writer 转译时直接读取本部分，不再依赖 `definition` 散文软提取。

---

## 1. 第一部分：定量风格分析报告（定量层 11 节）

**每节统一结构**：命名型总起句 + 因果诊断段（120–250 字），完成"数值并列 → 共振/矛盾指认 → 机制命名 → 阅读效果"的因果链；禁止纯数值罗列（详见 references/quality-baseline.md）。运行时至少硬校验 1.1–1.11 标题、非空正文、JSON 结构和数值冲突；生产报告应按质量基准完成完整篇幅与因果诊断。

| 章节 | 核心内容 | 关键机器指标 | 定性解读要求 |
|---|---|---|---|
| 1.1 | 文本基础概况 | 总字符数、章节数、句数、段数、噪音过滤占比 | 题材定性，禁止出现原作者角色扮演绑定 |
| 1.2 | 句式结构特征 | 平均/中位句长、短句率(≤10字)、长句率(≥50字) | 句长分档（极短/中短/中长/长句）与动势解读 |
| 1.3 | 段落与节奏结构 | 平均段长、极短段率(≤8字)、场景切换密度 | 换行习惯与叙事呼吸节奏 |
| 1.4 | 对话与叙事比例 | 对话字符占比、标签频次表、道:说比 | 互动驱动力与对话标签动词化倾向 |
| 1.5 | 标点符号使用 | 每千字标点密度（省略号/破折号按次计）、逗句比 | 情绪外放度与标点功能分配习惯 |
| 1.6 | 修辞手法 | 比喻/反问/排比密度（比喻按含显式喻词的句子计） | 修辞引擎（功能转译 vs 铺陈装饰） |
| 1.7 | 视角与叙事 | 第三/第一人称代词计数 | 镜头距离与推拉层次 |
| 1.8 | 描写密度 | 动作/心理/环境**主导句**计数、动作:心理比 | 驱动模式（动作事件 vs 内心意识流） |
| 1.9 | 角色对话风格 | 角色声纹表（高置信自动建卡 + 低置信清单） | 原型化标签呈现，不得出现原名 |
| 1.10 | 世界观与词汇 | 高频实义词群（自适应阈值） | 意象类型化提炼，禁止引用原专名 |
| 1.11 | 风格标记 | 3-6 条核心标记 | 每条必须有定量数据支撑 |

---

## 2. 第二部分：核心写作技法提取（技法调用卡层）

包含 3–6 张技法调用卡，与 `novel-writer` 人格「五、技法卡」直接对齐（下游自 3–6 张中选 ≤5 张）。

**技法的唯一定义**：句子/段落/标点/对话标签/描写配比/视角调度层面的可执行行文机制。
情节梗概或题材设定（如"某类体系的构建流程""某类冲突的升级路径"）不是技法，
会被 `check_card_content_quality` 内容闸门直接拒绝。

```json
{
  "id": "T01",
  "name": "技法名称（体现行文机制，非空泛词）",
  "definition": "一句话核心定义：行文层机制 + 产生的阅读效果",
  "serves_purpose": "本卡服务的阅读效果（对应第〇部分读者契约的哪一条）",
  "trigger": "写作场景出现什么具体信号时调用（可当场判断）",
  "steps": [
    "执行要点1（可直接照做）",
    "执行要点2",
    "执行要点3"
  ],
  "boundary": "失效边界三要素：禁用场景 + 退化成因 + 规避动作",
  "counterexample": "反例或禁忌（无则显式写'未发现明确反例'）",
  "evidence": [
    {
      "chunk_id": "c003",
      "quote": "原文引用（6–80字，须能在 chunk 中规范化字符串命中）",
      "metric": "对应定量指标名（如 tag_frequencies / punc_dash）",
      "note": "一句'该句如何体现此技法'的注解"
    }
  ],
  "transferability": "high",
  "confidence": "high"
}
```

硬性要求：
- 每张卡 ≥2 条证据，`metric` 字段必填且指向真实指标；全部证据均缺 `metric` 将被内容闸门直接拒绝。
- 每条证据附 `note` 注解，说明该句如何体现技法。
- 至少一张卡给出跨时期双锚点证据，证明技法为全书稳定特征。
- `serves_purpose` 必填：缺失将被内容闸门拒绝（10.0.0 起）。
- 内容闸门（`check_card_content_quality`）要求：定义/步骤含行文层机制词、触发条件非空、失效边界具备实质内容、引文 ≤80 字（与锚点池上限对齐）。

---

## 3. 公开 / 私有产物边界

`report.json` 默认使用 `artifact_policy: "public_sanitized"`：

- `quantitative_features` 递归移除 `sample_quotes`、`merged_aliases`、`excerpt` 等原文或声纹轨迹字段；**高/低置信说话人名单（原始人名轨迹）一律不进入公开 JSON**（原型化口吻仅在 1.9 散文与 `dialogue_review` 呈现）。
- 技法卡保留 `chunk_id`、`metric`、`note`、`era`、`verification_status`，但 `quote` 输出为“已校验证据（内容已隐藏）”；
- Markdown 的证据引文只保留锚点和验证占位文本，行尾说明仍执行脱敏；
- 公开 `desensitization_map` 使用中性候选编号，不暴露原始映射键；
- 默认脱敏头/Meta 仅写 `WORK_xxxx`（`meta.work_id`），真名与真标题不进入任何公开头部、正文或结构化字段；真名仅 `allow_author_identity/raw` 私有模式出现。

脱敏映射与 manifest sidecar 按报告名作用域落盘（`{base_name}_desensitization_map.json` / `{base_name}_manifest.json`），同目录多次 finalize（多报告→一人格）互不覆盖。

只有显式设置 `options.include_raw_evidence=true` 时，才额外生成 `*_private_evidence.json`。该 sidecar 保存原始 evidence store、原始技法卡和内部映射，不能作为公开报告发布。

`artifact_policy` 取值：

- `public_sanitized`（默认）：Markdown 与 JSON 均已脱敏，证据正文隐藏；
- `raw`：调用方显式关闭脱敏（`desensitize=False`）时。MD/JSON 不做专名映射，产物仅限私有使用；结构化裁剪（sample_quotes 等）仍然生效；
- 私有原文 sidecar 自身的 `artifact_policy` 为 `private_raw_evidence`，不可公开。

`report.json` 同时携带：`version`（渲染器包版本）、`provenance`（fallback 采样标记、覆盖率、时期数、占位符注册表快照）、`validation_summary`（四重校验与渲染终检结果 + quality 质量自评 + warnings）、`fidelity`（保真闭环结果，如启用）、`claims`（可选扩展层，仅在 LLM 响应携带时校验与透出）、`artifact_diagnostics`（映射错误/警告计数，诊断用）。`status: passed` 而 `publishable: failed` 是合法组合（契约合规但深度未达生产基准）：quality 自评不阻断发布，是否返工由调用方决定。`meta.author_name` 仅在 `allow_author_identity=true` 时出现；默认脱敏模式下身份不出现在任何结构化字段。`_rejected.md` 与 prepare 中间 JSON 含未脱敏原文与完整证据库，仅限私有保存。

`validation_summary` 与 `finalize_analysis` 返回值分层一致：`errors` 阻断（不生成正式报告）、`warnings` 提示、`quality`/`publishable` 事后自评。被拒时返回值额外携带 `repair_prompt`（错误清单+修法+可引用证据菜单+输出契约速查），追加到同一会话重试即可；`prepare_result.prepare_meta.prepare_schema_version` 记录阶段契约版本，finalize 开工前先用 `validate_prepare_result` 校验必返字段。

引文回验契约为「规范化包含命中（最短 6 字，上限 80 字）」：引文经空白/引号/破折号归一后须在语料中整体命中（模块常量 `MIN_QUOTE_CHARS = 6` 可回调）；短于 6 字的片段一律降级，不得充当已验证锚点。

`technique_cards[].evidence[].era` 由校验器按语料实测重推导（引文在采样文本中的精确偏移 → 时期区间），LLM 自报时期仅在偏离时提示后覆盖；跨期证据按卡校验——至少一张卡自身拥有两个不同时期的严格命中证据。

## 4. 第三部分：作家创作思维与宏观心智（思维层）

固定 6 个宏观心智维度 + 1 个题材适配边界：

1. **注意力顺序 (attention_order)**：进入场景时最先看见什么（人/物/关系/动作）。
2. **信息控制 (info_control)**：线索何时释放、如何隐藏、设问机制。
3. **冲突升级 (conflict_escalation)**：压力如何阶梯式加码。
4. **代价管理 (cost_management)**：获益、成长或胜利需要付出什么代价。
5. **收束方式 (closure)**：场景或章节结尾的状态变化模式与悬念钩子。
6. **长线布局 (long_arc)**：伏笔回收周期与卷级不可逆变化倾向（须引用 ≥2 组不同时期锚点对比）。
7. **题材适配边界 (adaptation_boundary)**：适合与不适合的叙事题材。
