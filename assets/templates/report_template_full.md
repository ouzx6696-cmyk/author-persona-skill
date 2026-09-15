# 《{{work_title}}》风格能力解构报告

> **报告契约**：四层契约 · 脱敏 · 证据锚点 · 保真闭环
> **分析对象**：{{work_title}}（来源作者标记：{{author_name}}）
> **采样范围**：{{sample_range_desc}}
> **降噪过滤**：已清洗平台寄语与格式噪音（噪音占比: {{noise_ratio_pct}}）
> **产物策略**：public_sanitized · {{work_id}}
> **校验状态**：schema {{schema_status}} / 脱敏 {{desens_status}} / 数值审计 {{numeric_status}}（质量自评与校验摘要见 report.json 的 quality / validation_summary 字段）

---

## 第〇部分：作家定义与读者契约（作家契约层）

（本节由 JSON 机器数据块的 writer_contract 单一真源渲染）

{{writer_contract_markdown}}

---

## 第一部分：定量风格分析报告（定量层）

### 1.1 文本基础概况
{{text_summary_interpretation}}

### 1.2 句式结构特征
{{sentence_structure_interpretation}}

### 1.3 段落与节奏结构
{{paragraph_rhythm_interpretation}}

### 1.4 对话与叙事比例
{{dialogue_features_interpretation}}

### 1.5 标点符号使用
{{punctuation_density_interpretation}}

### 1.6 修辞手法
{{rhetoric_features_interpretation}}

### 1.7 视角与叙事
{{perspective_narration_interpretation}}

### 1.8 描写密度
{{description_density_interpretation}}

### 1.9 角色对话风格
{{character_dialogue_interpretation}}

### 1.10 世界观与词汇
{{worldview_imagery_interpretation}}

### 1.11 风格标记
{{style_markers_list}}

---

## 第二部分：核心写作技法提取（技法调用卡层）

（本节由 JSON 机器数据块的 technique_cards 单一真源渲染）

{{technique_cards_markdown}}

---

## 第三部分：作家创作思维与宏观心智（思维层）

（本节由 JSON 机器数据块的 thinking_layer 单一真源渲染）

{{thinking_layer_markdown}}

<!-- 可选：保真闭环附录（trial_text 触发时由渲染器追加）{{fidelity_appendix}} -->

<!-- 附录 A/B/C 由渲染器在四层正文之后追加，顺序固定、标题不变：
     A 跨期对比矩阵（实测演变量）
     B 定量扩展（低层测量层与知识候选）
     C 分身配套产物（平台部署配置 + 三套风格模板摘要）
     三者均只读公开侧数据，不引入新的字符串来源。 -->

## 附录 A：跨期对比矩阵（实测演变量）

| 维度 | 开头 | 发展 | 成熟 | 均值 | 趋势 |
|---|---|---|---|---|---|
| 平均句长 | {{era_avg_sent_len_0}} | {{era_avg_sent_len_1}} | {{era_avg_sent_len_2}} | — | 由各期数值的斜率与波动幅度判定（上升/下降/波动/稳定） |
| 短句率 | … | … | … | … | … |
| 长句率 | … | … | … | … | … |
| 平均段长 | … | … | … | … | … |
| 对话占比 | … | … | … | … | … |
| 词汇丰富度 | … | … | … | … | … |

## 附录 B：定量扩展（低层测量层与知识候选）

### B.1 可读性与词汇丰富度

| 指标 | 实测值 |
|---|---|
| 可读性分级 | {{readability_level}} |
| 杨承淑指数 | {{yang_chengshu_index}} |
| Flesch-Kincaid | {{flesch_kincaid_grade}} |
| Gunning-Fog | {{gunning_fog_index}} |
| SMOG | {{smog_index}} |
| 平均句长（字） | {{avg_sentence_length_chars}} |
| 平均词长（字） | {{avg_word_length_chars}} |
| 复杂词比（≥4 字） | {{complex_word_ratio}} |
| TTR（全词） | {{ttr}} |
| TTR（过滤后） | {{ttr_filtered}} |
| Hapax 比 | {{hapax_ratio}} |

### B.2 句法复杂度与情感

| 指标 | 实测值 |
|---|---|
| 平均分句数/句 | {{avg_clauses_per_sentence}} |
| 从属分句占比 | {{subordinate_ratio}} |
| 并列分句占比 | {{coordinate_ratio}} |
| 情感平衡值 | {{sentiment_balance}} |
| 实体密度 | {{entity_density}} |

### B.3 词长与词性分布

| 指标 | 实测值 |
|---|---|
| 名词占比 | {{noun_ratio}} |
| 动词占比 | {{verb_ratio}} |
| 形容词占比 | {{adjective_ratio}} |

### B.4 世界观词汇与特色系统

> 各类词汇本体为原始专名，公开产物只列条数；门槛 `count>5 且 len>=2`，每类上限 10 项。

| 类别 | 命中条数 |
|---|---|
| 核心角色 | … |
| 核心设定 | … |
| 力量体系 | … |
| 组织势力 | … |
| 地域场景 | … |

### B.5 语义子维度

| 指标 | 实测值 |
|---|---|
| 对话功能·信息交换 | … |
| 对话功能·冲突对抗 | … |
| 对话功能·情感表达 | … |
| 对话功能·日常闲聊 | … |
| POV 稳定性 | … |

### B.6 维度间关联与风格候选

> **本节为候选解读，不具权威性**：信号与候选由维度间规则派生，须由本次实测数值落地后才能采用。

- 维度间关联信号：…
- 风格 DNA 候选（降序，非权威）：…
- 通用禁用词（AI 腔痕迹）：总而言之、综上所述、值得注意的是…

## 附录 C：分身配套产物

### C.1 平台部署配置（由实测特征派生）

| 平台 | 温度 | max_tokens | 落位 |
|---|---|---|---|
| dify | … | … | System Prompt |
| coze | … | … | 人设与回复逻辑 > 人设词 |
| solo | … | … | System Prompt |
| chatgpt | … | … | Custom Instructions / System |
| claude | … | … | System Prompt |

### C.2 三套可复用风格模板

| 模板 | 用途 |
|---|---|
| identification | 风格识别：五维匹配度 1–10；综合 <6 分必须给出 ≥3 条修改建议 |
| transfer | 风格转写：六条转写规则 + 每 300 字内至少 1 次对话或动作，末尾附实测对照 |
| dialogue_generation | 对话生成：六条规则，按原型口吻与实测平均台词长度切分轮次 |
