# 《{{work_title}}》风格能力解构报告

> **报告版本**：v10.2.0 (四层契约 · 脱敏 · 证据锚点 · 保真闭环)
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
