# -*- coding: utf-8 -*-
"""Technique Card definitions, schema validation, content heuristics, and rendering."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Content-level quality heuristics: a technique card must describe a sentence /
# paragraph / punctuation / dialogue-tag level *writing mechanism*, never a
# plot event or genre premise. This is the gate that keeps "how the author
# writes" separate from "what the story is about".
# ---------------------------------------------------------------------------

CRAFT_TERMS = [
    # 句法层
    "句长", "短句", "长句", "分句", "从句", "句子", "单句", "句式", "每句", "问句",
    # 词汇/词性层
    "动词", "副词", "名词", "形容词", "代词", "及物", "修饰词", "词性",
    # 段落层
    "段落", "段长", "换行", "分段", "极短段", "单句成段",
    # 标点层
    "标点", "逗号", "句号", "省略号", "破折号", "感叹号", "问号", "冒号",
    # 对话层
    "对话标签", "标签", "说话人", "对白", "台词", "口癖", "声纹",
    "设问", "反问", "疑问", "自问",
    # 描写/修辞层
    "比喻", "排比", "反复", "白描", "动作描写", "心理描写", "环境描写", "外貌描写",
    "独白", "内心", "外化", "感官", "通感", "意象",
    # 视角/镜头
    "视角", "人称", "限知", "全知", "镜头", "景别",
    # 节奏结构
    "节奏", "转场", "收束", "钩子", "留白", "悬念", "铺垫", "信息密度", "节拍",
    # 补充机制词：覆盖白描/点染/引语类语义合格的行文表述，降低词典式判断误拒
    "白描", "点染", "点题", "引语", "口吻", "铺陈", "动词链", "连用", "句群", "俗谚", "口头禅",
]

PLOT_DOMAIN_TERMS = [
    "功法", "修炼", "升级", "突破", "打脸", "夺嫡", "王朝", "帝国", "战争", "战役",
    "发明", "工业", "制度", "种田", "系统", "穿越", "副本", "秘境", "宝藏", "装备",
    "魔法体系", "神明", "教廷", "复仇", "夺宝",
]

# 引文长度上限与锚点池最长 80 字对齐（rhetoric 比喻锚 8-80、对话行 ≤80），
# 避免 LLM 原样引用 51-80 字池内锚点被拒、截断后又因子串匹配判 valid 的错配。
QUOTE_MAX_CHARS = 80


def check_card_content_quality(card_dict: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Validate that a card describes an executable writing mechanism."""
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(card_dict, dict):
        return (["Technique card must be a JSON object"], [])

    cid = str(card_dict.get("id", "?")).strip() or "?"
    name = str(card_dict.get("name", ""))
    definition = str(card_dict.get("definition", ""))
    trigger = str(card_dict.get("trigger", "")).strip()
    boundary = str(card_dict.get("boundary", "")).strip()
    steps = card_dict.get("steps", [])
    steps_text = " ".join(str(s) for s in steps) if isinstance(steps, list) else str(steps)
    body = f"{name} {definition} {steps_text}"

    craft_hits = sorted({t for t in CRAFT_TERMS if t in body})
    plot_hits = sorted({t for t in PLOT_DOMAIN_TERMS if t in body})
    if not craft_hits:
        errors.append(f"技法卡 {cid}: 定义与步骤中未检测到行文层机制词，疑似情节梗概或题材设定")
    elif len(plot_hits) >= 2:
        # 有机制词但混入多个题材域词：不整卡拒绝，降置信并提示复核，
        # 避免词典式判断误伤语义合格的行文机制卡
        warnings.append(f"技法卡 {cid}: 定义/步骤含多个题材域词 {plot_hits}，置信度降级处理")
    if not trigger or trigger in {"需要时", "合适的时候", "看情况"}:
        errors.append(f"技法卡 {cid}: 缺少可执行触发条件")

    if not str(card_dict.get("serves_purpose", "")).strip():
        errors.append(f"技法卡 {cid}: 缺少 serves_purpose（本卡服务的阅读效果）")

    if len(boundary) < 4 or boundary in {"无", "暂无", "未发现", "-"}:
        errors.append(f"技法卡 {cid}: 失效边界缺失或无实质内容")

    evidence = card_dict.get("evidence", [])
    if not isinstance(evidence, list):
        errors.append(f"技法卡 {cid}: evidence 必须是列表")
        return errors, warnings
    for idx, ev in enumerate(evidence):
        if not isinstance(ev, dict):
            errors.append(f"技法卡 {cid}: 证据[{idx}] 必须是对象")
            continue
        metric = str(ev.get("metric", "")).strip()
        if not metric:
            errors.append(f"技法卡 {cid}: 证据[{idx}] 缺少 metric 指标标注（硬约束清单 #3）")
        else:
            from ..report.metrics import metric_token_from_label
            if metric_token_from_label(metric) is None:
                errors.append(f"技法卡 {cid}: 证据[{idx}] 的 metric 无法解析为已注册指标：{metric}（硬约束清单 #3）")
        if not str(ev.get("note", "")).strip():
            errors.append(f"技法卡 {cid}: 证据[{idx}] 缺少 note 证据注解（硬约束清单 #1）")
        if len(str(ev.get("quote", "")).strip()) > QUOTE_MAX_CHARS:
            errors.append(f"技法卡 {cid}: 证据[{idx}] 的 quote 过长（最多 {QUOTE_MAX_CHARS} 字，硬约束清单 #2）")

    return errors, warnings


@dataclass
class EvidenceItem:
    chunk_id: str
    quote: str
    metric: str = ""
    note: str = ""
    era: str = ""
    verification_status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "quote": self.quote,
            "metric": self.metric,
            "note": self.note,
            "era": self.era,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceItem":
        return cls(
            chunk_id=str(data.get("chunk_id", "")).strip(),
            quote=str(data.get("quote", "")).strip(),
            metric=str(data.get("metric", "")).strip(),
            note=str(data.get("note", "")).strip(),
            era=str(data.get("era", "")).strip(),
            verification_status=str(data.get("verification_status", "pending")).strip().lower(),
        )


@dataclass
class TechniqueCard:
    id: str
    name: str
    definition: str
    trigger: str
    steps: List[str]
    boundary: str
    evidence: List[EvidenceItem]
    counterexample: str
    # 本卡服务的阅读效果：下游 novel-writer 转译时按此回指读者契约（P1-E1）。
    serves_purpose: str = ""
    transferability: str = "high"  # high | mid | low
    confidence: str = "high"       # high | mid | low

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "definition": self.definition,
            "trigger": self.trigger,
            "steps": list(self.steps),
            "boundary": self.boundary,
            "evidence": [e.to_dict() if isinstance(e, EvidenceItem) else e for e in self.evidence],
            "counterexample": self.counterexample,
            "serves_purpose": self.serves_purpose,
            "transferability": self.transferability,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TechniqueCard":
        evidence_raw = data.get("evidence", [])
        evidence_items = []
        if isinstance(evidence_raw, list):
            for item in evidence_raw:
                if isinstance(item, dict):
                    evidence_items.append(EvidenceItem.from_dict(item))
                elif isinstance(item, str):
                    evidence_items.append(EvidenceItem(chunk_id="", quote=item))

        steps_raw = data.get("steps", [])
        if isinstance(steps_raw, list):
            steps = [str(s).strip() for s in steps_raw if str(s).strip()]
        elif isinstance(steps_raw, str):
            steps = [s.strip() for s in steps_raw.splitlines() if s.strip()]
        else:
            steps = []

        return cls(
            id=str(data.get("id", "")).strip(),
            name=str(data.get("name", "")).strip(),
            definition=str(data.get("definition", "")).strip(),
            trigger=str(data.get("trigger", "")).strip(),
            steps=steps,
            boundary=str(data.get("boundary", "")).strip(),
            evidence=evidence_items,
            counterexample=str(data.get("counterexample", "")).strip(),
            serves_purpose=str(data.get("serves_purpose", data.get("阅读效果", ""))).strip(),
            transferability=str(data.get("transferability", "high")).lower().strip(),
            confidence=str(data.get("confidence", "high")).lower().strip(),
        )

    def validate(self, min_evidence: int = 2) -> Tuple[bool, List[str]]:
        """Validate technique card according to the report contract schema."""
        errors: List[str] = []

        if not self.name or self.name in {"描写细腻", "文笔优美", "情节紧凑", "未命名技法"}:
            errors.append(f"Card {self.id}: name must be distinctive, got '{self.name}'")

        if not self.definition:
            errors.append(f"Card {self.id}: definition cannot be empty")

        if not self.trigger or self.trigger in {"需要时", "合适的时候", "看情况"}:
            errors.append(f"Card {self.id}: trigger must be an actionable scene signal, got '{self.trigger}'")

        if len(self.steps) < 3 or len(self.steps) > 5:
            errors.append(f"Card {self.id}: steps count should be between 3 and 5 (got {len(self.steps)})")

        if not self.boundary:
            errors.append(f"Card {self.id}: boundary cannot be empty")

        if len(self.evidence) < min_evidence:
            errors.append(f"Card {self.id}: evidence count must be >= {min_evidence}, got {len(self.evidence)}")
        else:
            for idx, ev in enumerate(self.evidence):
                if not ev.quote:
                    errors.append(f"Card {self.id}: evidence[{idx}] quote cannot be empty")
                # Callers may construct EvidenceItem directly without
                # the enriched note/status fields; the report content gate
                # performs the strict public-contract check.
                if not ev.metric:
                    errors.append(f"Card {self.id}: evidence[{idx}] metric cannot be empty")

        if not self.counterexample:
            errors.append(f"Card {self.id}: counterexample must be present or explicitly stated as '未发现明确反例'")

        if not self.serves_purpose:
            errors.append(f"Card {self.id}: serves_purpose cannot be empty (state which reader effect this card serves)")

        if self.transferability not in {"high", "mid", "low"}:
            errors.append(f"Card {self.id}: transferability must be high/mid/low, got '{self.transferability}'")

        if self.confidence not in {"high", "mid", "low"}:
            errors.append(f"Card {self.id}: confidence must be high/mid/low, got '{self.confidence}'")

        return (len(errors) == 0, errors)

    def render_markdown(self) -> str:
        """Render technique card in prose markdown format."""
        lines = [
            f"### {self.id}：{self.name}",
            f"- **定义**：{self.definition}",
            f"- **本卡服务的阅读效果**：{self.serves_purpose}",
            f"- **触发条件**：{self.trigger}",
            "- **写法要点**：",
        ]
        for step_no, step in enumerate(self.steps, 1):
            lines.append(f"  {step_no}. {step}")
        lines.append(f"- **失效边界**：{self.boundary}")
        lines.append(f"- **反例/禁忌**：{self.counterexample}")
        lines.append(f"- **迁移性 / 置信度**：{self.transferability.upper()} / {self.confidence.upper()}")
        lines.append("- **证据支撑**：")
        for ev in self.evidence:
            ref = f"[{ev.chunk_id}] " if ev.chunk_id else ""
            metric = f" ({ev.metric})" if ev.metric else ""
            note = f" — 注解：{ev.note}" if ev.note else ""
            lines.append(f"  - {ref}“{ev.quote}”{metric}{note}")
        return "\n".join(lines)
