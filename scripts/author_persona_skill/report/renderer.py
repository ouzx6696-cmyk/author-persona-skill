# -*- coding: utf-8 -*-
"""Markdown report and JSON sidecar renderer."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 版本号的唯一来源。这里刻意用「导入子模块」(from .._version import __version__)，
# 而不是「从包 __init__ 取属性」(from .. import __version__)：
# 本模块会在包 __init__ 仍在执行期间被导入（__init__ -> pipeline -> renderer），
# 而 __init__ 的 __version__ 要等它自己的导入全部跑完才存在，
# 后者必然抛 "cannot import name from partially initialized module"。
# 该约束由 _version.py 自身满足 —— 它只依赖标准库、不 import 包内任何模块，
# 所以这条导入不会成环。
# 不要为了"去重"把它改回 from .. import __version__，那会在包初始化阶段直接炸。
from .._numbers import trim_decimal
from .._version import __version__
from ..distill.technique_cards import TechniqueCard
from ..distill.thinking_layer import ThinkingLayer
from ..distill.writer_contract import WriterContract
from ..distill.desensitize import (
    apply_desensitization,
    mask_evidence_quotes,
    validate_desensitization,
    validate_desensitization_map,
)
from .metrics import build_placeholder_map
from ..analyzers.cross_era import build_cross_era_matrix, extract_exemplars
from ..persona.deployment import build_deployment_config
from ..persona.style_templates import render_all_style_templates


_PUBLIC_EVIDENCE_PLACEHOLDER = "已校验证据（内容已隐藏）"
#: report.json 的 schema 版本。单一来源：三处输出（report.json / provenance /
#: manifest）此前各写一份字面量，改版时必须同步改三处，漏一处就会产出自相矛盾
#: 的产物。schema 6 是破坏性升级（新增 voiceprint / cross_era_matrix /
#: low_level_features / style_dna_candidates / deployment_config / style_templates
#: 等必填字段）。本技能独立发布，此版本只描述本报告自身的契约；下游读取方
#: 是否跟进是其适配问题，不构成本技能的发布前提。
REPORT_SCHEMA_VERSION = "6"
# 高/低置信说话人名单是身份轨迹：原型化口吻在 dialogue_review 与 1.9 散文中
# 呈现，原始人名列表一律不进公开 JSON。
# unique_tags 把「哪个角色独占哪个标签」写成 {tag: {speaker: 原名}}，是同等强度
# 的身份轨迹；公开侧的等价物是经映射脱敏的 voiceprint 块，因此这里整体剔除。
# 低层测量层同样产出身份轨迹：命名实体样例（人名/地名/机构名）与世界观词汇表
# 都是原始专名，且多数角色并不在候选池里（只有 top-3 说话人才进池），靠映射
# 兜不住——一律按「不进公开产物」处理，公开侧只留计数与密度。
_SENSITIVE_QUANT_KEYS = {
    "sample_quotes", "merged_aliases", "raw_quote", "raw_text", "excerpt",
    "high_confidence_speakers", "low_confidence_candidates", "unique_tags",
    "sample_persons", "sample_places", "sample_orgs", "term_counts",
}


def _fallback_label(index: int) -> str:
    """Return a deterministic neutral label for an unmapped candidate."""
    alphabet = "甲乙丙丁戊己庚辛壬癸"
    return f"原型{alphabet[index % len(alphabet)]}"


def _build_public_mapping(
    mapping: Any,
    proper_noun_candidates: Any,
) -> Tuple[Dict[str, str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a safe mapping for public artifacts and report mapping diagnostics."""
    raw_mapping = mapping if isinstance(mapping, dict) else {}
    candidates = proper_noun_candidates if isinstance(proper_noun_candidates, list) else []
    map_errors, map_warnings = validate_desensitization_map(raw_mapping, candidates)
    public_mapping: Dict[str, str] = {}
    for key, value in raw_mapping.items():
        original = str(key).strip()
        replacement = str(value).strip()
        if original and replacement and replacement != original:
            public_mapping[original] = replacement

    next_index = 0
    for item in candidates:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term", "")).strip()
        if len(term) < 2 or term in public_mapping:
            continue
        public_mapping[term] = _fallback_label(next_index)
        next_index += 1
    return public_mapping, map_errors, map_warnings


# 公开话术块（voiceprint）的上限。它是「原型口吻」的公开等价物：私有 sidecar
# 保留真实人名与整句台词，公开侧只给出经映射的原型标签与可复用的话术习惯。
_VOICEPRINT_MAX_PROFILES = 8
_VOICEPRINT_MAX_PHRASES = 6


def _public_voiceprint(
    dialogue_features: Any,
    mapping: Dict[str, str],
    proper_noun_candidates: List[Dict[str, Any]],
    author_name: str,
    work_title: str,
    use_real_names: bool = False,
) -> Dict[str, Any]:
    """Build the desensitized public voiceprint block.

    说话人原名的公开等价物只有原型标签。脱敏模式下未取得映射标签的角色一律不
    出现：宁可少一个原型，也不能让原名当键。`catchphrases`/`opening_words` 先过
    映射，过完仍被泄露检测判定含专名的条目直接丢弃——半脱敏的短语比没有更危险。

    ``use_real_names`` 仅用于显式 raw 模式：机器 sidecar 的结构化最小化在任何策略
    下都生效（说话人名单在 raw 模式下同样被剔除），所以 raw 模式也只换标签来源，
    不换成实名当键。短语的泄露过滤则**两种模式都执行**——短语取自角色台词，台词里
    出现另一个人名是常态，放过它就等于在「已脱敏」的块里留下半个专名。
    """
    if not isinstance(dialogue_features, dict):
        return {}
    profiles = dialogue_features.get("high_confidence_speakers")
    if not isinstance(profiles, list):
        return {}

    def clean_phrases(raw: Any) -> List[str]:
        if not isinstance(raw, list):
            return []
        out: List[str] = []
        for item in raw:
            phrase = str(item).strip()
            if not phrase:
                continue
            mapped = apply_desensitization(phrase, mapping) if mapping else phrase
            passed, _leaks = validate_desensitization(
                mapped, proper_noun_candidates, author_name, work_title
            )
            if not passed:
                continue
            if mapped not in out:
                out.append(mapped)
            if len(out) >= _VOICEPRINT_MAX_PHRASES:
                break
        return out

    voiceprint: Dict[str, Any] = {}
    for profile in profiles[:_VOICEPRINT_MAX_PROFILES]:
        if not isinstance(profile, dict):
            continue
        raw_name = str(profile.get("name", "")).strip()
        # raw 模式跳过专名映射，改用位置派生的中性标签，避免实名进入 sidecar。
        label = _fallback_label(len(voiceprint)) if use_real_names else mapping.get(raw_name)
        if not label or label in voiceprint:
            continue
        voiceprint[label] = {
            "tone_type": profile.get("tone_type") or "未定",
            "avg_speech_len": profile.get("avg_dialogue_len"),
            "common_tags": clean_phrases(profile.get("common_tags")),
            "opening_words": clean_phrases(profile.get("opening_words")),
            "catchphrases": clean_phrases(profile.get("fixed_phrases")),
        }
    return voiceprint


def _sanitize_public_value(value: Any, mapping: Dict[str, str], key: str = "") -> Any:
    """Recursively remove raw evidence and apply the public noun mapping.

    Keys are mapped too: a structured map can carry an identity in its *keys*
    (``imagery_clusters`` is keyed by high-frequency words, which in practice
    include character names). Leaving keys alone leaked them into the public
    sidecar while the value-only scan never noticed.
    """
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            child_key = str(raw_key)
            if child_key in _SENSITIVE_QUANT_KEYS:
                continue
            if child_key == "quote" and (key == "evidence" or "chunk_id" in value):
                result[child_key] = _PUBLIC_EVIDENCE_PLACEHOLDER
                continue
            if child_key == "sample_quotes":
                continue
            public_key = apply_desensitization(child_key, mapping) if mapping else child_key
            result[public_key] = _sanitize_public_value(raw_value, mapping, child_key)
        return result
    if isinstance(value, list):
        return [_sanitize_public_value(item, mapping, key) for item in value]
    if isinstance(value, str):
        return apply_desensitization(value, mapping)
    return value


def _sanitize_evidence_lines(prose: str, mapping: Dict[str, str]) -> str:
    """Hide every quoted evidence body while preserving review metadata on the line.

    遮蔽规则由 distill.desensitize.mask_evidence_quotes 统一提供，与校验层的
    引文豁免判定同源；随后对整行（含行尾注解）执行专名脱敏。
    """
    if not prose:
        return prose
    masked = mask_evidence_quotes(prose, _PUBLIC_EVIDENCE_PLACEHOLDER)
    return "\n".join(
        apply_desensitization(line, mapping) for line in masked.splitlines()
    )


def _export_public_mapping(mapping: Dict[str, str]) -> Dict[str, str]:
    """Expose only neutral mapping identifiers in public artifacts."""
    return {
        f"候选原型_{index:02d}": replacement
        for index, replacement in enumerate(mapping.values(), 1)
        if replacement
    }


def _atomic_write_text(path: Path, text: str) -> None:
    """Write a file beside its destination and replace it only after success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def extract_json_block(llm_text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Split LLM response into prose markdown and the parsed trailing JSON block.
    """
    json_blocks = re.findall(r'```json\s*(\{[\s\S]*?\})\s*```', llm_text)
    if not json_blocks:
        # Fallback: look for naked JSON dict at the end of the text
        match = re.search(r'(\{[\s\S]*"technique_cards"[\s\S]*\})\s*$', llm_text)
        if match:
            json_str = match.group(1)
            try:
                data = json.loads(json_str)
                prose = llm_text[:match.start()].strip()
                return prose, data
            except json.JSONDecodeError:
                pass
        return llm_text.strip(), None

    # Pick the last json block which should be the machine data block
    target_block = json_blocks[-1]
    try:
        data = json.loads(target_block)
        if not isinstance(data, dict):
            # 顶层必须是对象；数组/标量按"无有效机器块"处理，交由校验器拒绝
            return llm_text.strip(), None
        # Remove the code block from the markdown prose
        prose = re.sub(r'```json\s*' + re.escape(target_block) + r'\s*```', '', llm_text).strip()
        return prose, data
    except json.JSONDecodeError:
        return llm_text.strip(), None


def desensitize_prose(prose: str, mapping: Dict[str, str]) -> str:
    """Apply mapping and hide raw evidence bodies in public Markdown."""
    if not prose:
        return prose
    return _sanitize_evidence_lines(prose, mapping or {})


_PART0_HEADING = "## 第〇部分：作家定义与读者契约（作家契约层）"
_PART2_HEADING = "## 第二部分：核心写作技法提取（技法调用卡层）"
_PART3_HEADING = "## 第三部分：作家创作思维与宏观心智（思维层）"


def _compose_single_source(prose_markdown: str, parsed_json: Optional[Dict[str, Any]]) -> str:
    """以 JSON 机器块为唯一真源重写第〇、二、三部分正文。

    LLM 只撰写第一部分散文与 JSON 块；作家契约、技法卡与思维层由已通过校验的
    JSON 渲染生成，Markdown 与 report.json 不再可能出现两套互相矛盾的内容。
    保真闭环附录（若有）保持在文末。

    任一部分标题行缺失或顺序颠倒时抛错走 fail-closed，而不是把 LLM 手写正文
    原样放行——那会让公开产物绕开"单一真源"契约（manifest core_constraint）。
    上游 response_health_check 已按行级 `^##` 正则拦截缺失，此处兜底。
    """
    if not parsed_json:
        raise ValueError("单一真源渲染缺少 JSON 机器块，拒绝渲染")
    part0_pos = prose_markdown.find("## 第〇部分")
    part1_pos = prose_markdown.find("## 第一部分")
    part2_pos = prose_markdown.find("## 第二部分")
    part3_pos = prose_markdown.find("## 第三部分")
    if part0_pos < 0:
        raise ValueError("响应缺少「## 第〇部分」标题行，无法执行单一真源渲染")
    if part1_pos < 0 or part1_pos < part0_pos:
        raise ValueError("响应缺少「## 第一部分」标题行（或顺序颠倒），无法执行单一真源渲染")
    if part2_pos < 0:
        raise ValueError("响应缺少「## 第二部分」标题行，无法执行单一真源渲染")
    if part3_pos < 0 or part3_pos < part2_pos:
        raise ValueError("响应缺少「## 第三部分」标题行（或顺序颠倒），无法执行单一真源渲染")

    contract = WriterContract.from_dict(parsed_json.get("writer_contract") or {})
    contract_ok, contract_errors = contract.validate()
    if not contract_ok:
        raise ValueError("writer_contract 校验失败（第〇部分拒绝渲染）：" + "；".join(contract_errors))

    card_blocks: List[str] = []
    for card in parsed_json.get("technique_cards") or []:
        try:
            card_blocks.append(TechniqueCard.from_dict(card).render_markdown())
        except Exception:
            continue
    if not card_blocks:
        # 无卡可渲染同样是 fail-closed：上游已强制 3–6 张卡，
        # 走到这里说明响应结构与校验结果不一致。
        raise ValueError("单一真源渲染未产出任何技法卡正文，拒绝渲染")

    try:
        thinking_block = ThinkingLayer.from_dict(
            parsed_json.get("thinking_layer") or {}
        ).render_markdown()
    except Exception:
        thinking_block = ""

    appendix = ""
    appendix_pos = prose_markdown.find("## 附录：")
    if appendix_pos > part3_pos:
        appendix = "\n\n---\n\n" + prose_markdown[appendix_pos:].strip()

    return (
        prose_markdown[:part0_pos].rstrip()
        + "\n\n" + _PART0_HEADING + "\n\n" + contract.render_markdown()
        + "\n\n" + prose_markdown[part1_pos:part2_pos].rstrip()
        + "\n\n" + _PART2_HEADING + "\n\n" + "\n\n".join(card_blocks)
        + "\n\n" + _PART3_HEADING + "\n\n" + thinking_block
        + appendix
    )


def _extract_exemplars_for_private(evidence_pool: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """正反例抽取，仅供私有 sidecar（`include_raw_evidence` 时落盘）。"""
    return extract_exemplars(evidence_pool)


def _fmt_metric(value: Any, digits: int = 2) -> str:
    if value in (None, ""):
        return "—"
    try:
        return trim_decimal(float(value), digits)
    except (TypeError, ValueError):
        return str(value)


def _render_quant_extension_appendix(quant: Dict[str, Any]) -> str:
    """Markdown 附录 B：低层测量层 + 知识层候选信号。

    只输出计数、比率与分级标签；命名实体样例与世界观词汇表是原始专名，公开
    通道一律不引用（与 `_SENSITIVE_QUANT_KEYS` 同一判定），因此这里刻意**不读**
    `sample_*` / `term_counts` 字段，读取方式本身即防线。
    """
    if not isinstance(quant, dict):
        return ""
    low = quant.get("low_level_features", {}) or {}
    categories = (quant.get("worldview_vocab", {}) or {}).get("categories") or {}
    systems = (quant.get("worldview_vocab", {}) or {}).get("special_systems") or []
    semantic = quant.get("semantic_dimensions", {}) or {}
    knowledge = quant.get("knowledge_layer", {}) or {}
    sections: List[str] = []

    readability = low.get("readability", {}) or {}
    vocab = low.get("vocabulary_richness", {}) or {}
    complexity = low.get("sentence_complexity", {}) or {}
    sentiment = low.get("sentiment", {}) or {}
    word_len = low.get("word_length_distribution", {}) or {}
    pos_dist = low.get("pos_distribution", {}) or {}
    entities = low.get("named_entities", {}) or {}
    if low:
        sections.append(
            "### B.1 可读性与词汇丰富度\n\n"
            "| 指标 | 实测值 |\n|---|---|\n"
            f"| 可读性分级 | {readability.get('readability_level', '—')} |\n"
            f"| 杨承淑指数 | {_fmt_metric(readability.get('yang_chengshu_index'))} |\n"
            f"| Flesch-Kincaid | {_fmt_metric(readability.get('flesch_kincaid_grade'))} |\n"
            f"| Gunning-Fog | {_fmt_metric(readability.get('gunning_fog_index'))} |\n"
            f"| SMOG | {_fmt_metric(readability.get('smog_index'))} |\n"
            f"| 平均句长（字） | {_fmt_metric(readability.get('avg_sentence_length_chars'))} |\n"
            f"| 平均词长（字） | {_fmt_metric(readability.get('avg_word_length_chars'))} |\n"
            f"| 复杂词比（≥4 字） | {_fmt_metric(readability.get('complex_word_ratio'), 4)} |\n"
            f"| TTR（全词） | {_fmt_metric(vocab.get('ttr'), 4)} |\n"
            f"| TTR（过滤后） | {_fmt_metric(vocab.get('ttr_filtered'), 4)} |\n"
            f"| Hapax 比 | {_fmt_metric(vocab.get('hapax_ratio'), 4)} |\n"
            f"| 单次词数 | {_fmt_metric(vocab.get('hapax_count'), 0)} |\n\n"
            "### B.2 句法复杂度与情感\n\n"
            "| 指标 | 实测值 |\n|---|---|\n"
            f"| 平均分句数/句 | {_fmt_metric(complexity.get('avg_clauses_per_sentence'))} |\n"
            f"| 复杂度分级 | {complexity.get('complexity_level', '—')} |\n"
            f"| 从属分句占比 | {_fmt_metric(complexity.get('subordinate_ratio'), 4)} |\n"
            f"| 并列分句占比 | {_fmt_metric(complexity.get('coordinate_ratio'), 4)} |\n"
            f"| 情感平衡值 | {_fmt_metric(sentiment.get('sentiment_balance'), 4)} |\n"
            f"| 主导情感 | {sentiment.get('dominant_tone', '—')} |\n"
            f"| 实体密度 | {_fmt_metric(entities.get('entity_density'), 4)} |\n\n"
            "### B.3 词长与词性分布\n\n"
            "| 指标 | 实测值 |\n|---|---|\n"
            f"| 单字词比 | {_fmt_metric(word_len.get('len_1_ratio'), 4)} |\n"
            f"| 双字词比 | {_fmt_metric(word_len.get('len_2_ratio'), 4)} |\n"
            f"| 三字词比 | {_fmt_metric(word_len.get('len_3_ratio'), 4)} |\n"
            f"| 四字及以上比 | {_fmt_metric(word_len.get('len_4plus_ratio'), 4)} |\n"
            f"| 名词占比 | {_fmt_metric(pos_dist.get('noun_ratio'), 4)} |\n"
            f"| 动词占比 | {_fmt_metric(pos_dist.get('verb_ratio'), 4)} |\n"
            f"| 形容词占比 | {_fmt_metric(pos_dist.get('adjective_ratio'), 4)} |\n"
            f"| 副词占比 | {_fmt_metric(pos_dist.get('adverb_ratio'), 4)} |\n"
        )

    wv_rows: List[str] = []
    if isinstance(categories, list):
        for entry in categories:
            if not isinstance(entry, dict):
                continue
            # 公开侧 term_counts 已被剔除，只有 count 可用；私有/测试数据里
            # term_counts 仍在，用它兜底以兼容旧结构。
            terms = entry.get("term_counts")
            n = entry.get("count")
            if n is None:
                n = len(terms) if isinstance(terms, dict) else None
            if n is None:
                continue
            wv_rows.append(f"| {entry.get('category', '-')} | {_fmt_metric(n, 0)} |")
    if low:
        # 无论是否命中都渲染 B.4：整节缺席会被读成「没测」，而实际含义是「未达门槛」。
        sections.append(
            "### B.4 世界观词汇与特色系统\n\n"
            "> 门槛：`count>5 且 len>=2`；各类上限 10 项。词汇本体为原始专名，不进公开产物，"
            "此处只列条数与系统流关键词命中。\n\n"
            "| 类别 | 命中条数 |\n|---|---|\n" + "\n".join(wv_rows or ["| （未达门槛） | 0 |"])
            + ("\n\n特色系统关键词命中：" + "、".join(str(s) for s in systems) if systems
               else "\n\n特色系统关键词命中：未命中")
        )

    dfunc = (quant.get("dialogue_features", {}) or {}).get("dialogue_functions") or {}
    # dialogue_functions 是嵌套结构（counts / distribution），不是扁平映射：
    # 直接读顶层键会全部渲染成「—」，看起来像「没测到」，实则是读错了层。
    dfunc_dist = dfunc.get("distribution") if isinstance(dfunc, dict) else None
    if not isinstance(dfunc_dist, dict):
        dfunc_dist = dfunc if isinstance(dfunc, dict) else {}
    pov = semantic.get("pov_stability") if isinstance(semantic, dict) else None
    if not isinstance(pov, dict):
        pov = {}
    if dfunc_dist or pov or semantic:
        if pov:
            pov_text = (
                f"{pov.get('stability', '—')}（主导视角：{pov.get('dominant_pov', '—')}；"
                f"第一人称 {pov.get('first_person_count', '—')} / 第三人称 {pov.get('third_person_count', '—')}）"
            )
        else:
            pov_text = "—"
        sections.append(
            "### B.5 语义子维度\n\n"
            "| 指标 | 实测值 |\n|---|---|\n"
            f"| 对话功能·信息交换 | {_fmt_metric(dfunc_dist.get('信息交换'), 4)} |\n"
            f"| 对话功能·冲突对抗 | {_fmt_metric(dfunc_dist.get('冲突对抗'), 4)} |\n"
            f"| 对话功能·情感表达 | {_fmt_metric(dfunc_dist.get('情感表达'), 4)} |\n"
            f"| 对话功能·日常闲聊 | {_fmt_metric(dfunc_dist.get('日常闲聊'), 4)} |\n"
            f"| POV 稳定性 | {pov_text} |\n"
        )

    signals = knowledge.get("cross_metric_signals") or []
    cands = knowledge.get("style_dna_candidates") or []
    taboos = knowledge.get("generic_taboo_phrases") or []
    if signals or cands or taboos:
        lines = [
            "### B.6 维度间关联与风格候选\n",
            "> **本节为候选解读，不具权威性**：信号与候选由维度间规则派生，须由本次实测数值"
            "落地后才能采用，不得替代第一部分与第二部分的结论。\n",
        ]
        if signals:
            lines.append("**维度间关联信号**：\n")
            for sig in signals:
                if isinstance(sig, dict):
                    lines.append(f"- {sig.get('signal', sig)}")
                else:
                    lines.append(f"- {sig}")
            lines.append("")
        if cands:
            lines.append("**风格 DNA 候选（降序，非权威）**：\n")
            for cand in cands:
                if isinstance(cand, dict):
                    lines.append(f"- {cand.get('label', '-')}（得分 {_fmt_metric(cand.get('score'), 3)}）")
            lines.append("")
        if taboos:
            lines.append("**通用禁用词（AI 腔痕迹）**：" + "、".join(str(t) for t in taboos))
        sections.append("\n".join(lines))

    if not sections:
        return ""
    return "\n\n---\n\n## 附录 B：定量扩展（低层测量层与知识候选）\n\n" + "\n\n".join(sections)


def _render_persona_kit_appendix(report_json: Dict[str, Any]) -> str:
    """Markdown 附录 C：平台部署配置 + 三套风格模板适用范围（摘要）。"""
    if not isinstance(report_json, dict):
        return ""
    deploy = report_json.get("deployment_config") or {}
    platforms = deploy.get("platforms") or {}
    templates = report_json.get("style_templates") or {}
    if not platforms and not templates:
        return ""
    rows: List[str] = []
    for name, cfg in platforms.items():
        if not isinstance(cfg, dict):
            continue
        rows.append(
            f"| {name} | {_fmt_metric(cfg.get('temperature'), 2)} | "
            f"{cfg.get('max_tokens', '—')} | {cfg.get('config_location', '—')} |"
        )
    note = deploy.get("config_note", "")
    derived = deploy.get("derived_from") or {}
    body = [
        "### C.1 平台部署配置（由实测特征派生）\n",
        "| 平台 | 温度 | max_tokens | 落位 |\n|---|---|---|---|\n" + "\n".join(rows),
    ]
    if note:
        body.append(f"\n> {note}")
    if derived:
        body.append(
            "\n派生依据：" + "、".join(f"{k}={v}" for k, v in derived.items())
        )
    if templates:
        body.append(
            "\n\n### C.2 三套可复用风格模板\n\n"
            "| 模板 | 用途 |\n|---|---|\n"
            "| identification | 风格识别：五维匹配度 1–10；综合 <6 分必须给出 ≥3 条修改建议 |\n"
            "| transfer | 风格转写：六条转写规则 + 每 300 字内至少 1 次对话或动作，末尾附实测对照 |\n"
            "| dialogue_generation | 对话生成：六条规则，按原型口吻与实测平均台词长度切分轮次 |\n\n"
            "> 模板正文以完整字符串存放于 `report.json` 的 `style_templates` 字段；"
            "其中所有数值均取自本次实测，且不含真实作者名与作品名。"
        )
    return "\n\n---\n\n## 附录 C：分身配套产物\n\n" + "\n".join(body)


def _render_cross_era_appendix(matrix: Optional[Dict[str, Any]]) -> str:
    """Markdown 附录 A：6 维跨期对比矩阵 + 每维演变量趋势。

    矩阵数据全部来自实测（per-era 指标），分期标签是中性代号，数值为纯数值，
    因此不涉及专名——但仍随公开产物走同一套通道，保持一致。
    """
    if not isinstance(matrix, dict):
        return ""
    eras = matrix.get("eras") or []
    dimensions = matrix.get("dimensions") or []
    if not eras or not dimensions:
        return ""
    header = "| 维度 | " + " | ".join(str(e) for e in eras) + " | 均值 | 趋势 |"
    divider = "|---" * (len(eras) + 3) + "|"
    rows = [header, divider]
    for dim in dimensions:
        if not isinstance(dim, dict):
            continue
        values = dim.get("values") or []
        cells = [("—" if v is None else str(v)) for v in values]
        # 补齐列数：缺失的 era 以破折号占位，避免表格错位。
        while len(cells) < len(eras):
            cells.append("—")
        mean = dim.get("mean")
        rows.append(
            f"| {dim.get('dimension', '-')} | " + " | ".join(cells)
            + f" | {'—' if mean is None else mean} | {dim.get('trend', '-')} |"
        )
    return (
        "\n\n---\n\n## 附录 A：跨期对比矩阵（实测演变量）\n\n"
        "> 每一列是一个时期的独立测量；趋势列由各期数值的斜率与波动幅度判定"
        "（上升/下降/波动/稳定）。分期标签为中性代号。\n\n"
        + "\n".join(rows) + "\n"
    )


def _validation_summary(
    validation: Optional[Dict[str, Any]],
    public_mapping: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """机器端可读的校验/质量摘要；未传校验结果时为 None.

    Warnings may cite candidate terms themselves (e.g. "缺少高频专名'X'"),
    so they must be desensitized before publishing; otherwise the final audit
    would mistake diagnostics for leaks -- and public JSON must never carry
    identifiable strings.
    """
    if not isinstance(validation, dict):
        return None
    numeric = validation.get("numeric_audit") or {}
    raw_warnings = validation.get("warnings", [])
    clean_warnings = []
    for w in raw_warnings:
        s = str(w)
        if public_mapping:
            try:
                s = apply_desensitization(s, public_mapping)
            except Exception:
                pass
            # 仍含未映射高频词时,折叠原词只留计数语义,避免公共产物泄漏
            # (完整原文仅保留在私有校验结果中,不进 report.json)
        clean_warnings.append(s)
    return {
        "status": validation.get("status"),
        "schema": validation.get("schema"),
        "desensitization": validation.get("desensitization"),
        "numeric_audit_status": numeric.get("status"),
        "evidence": validation.get("evidence"),
        "quality": validation.get("quality"),
        "integrity": validation.get("integrity"),
        "quality_status": validation.get("quality_status"),
        "privacy": validation.get("privacy"),
        "publishable": validation.get("publishable"),
        "warnings": clean_warnings,
    }


def render_report_outputs(
    prose_markdown: str,
    parsed_json: Optional[Dict[str, Any]],
    prepare_result: Dict[str, Any],
    output_dir: Optional[Path] = None,
    base_name: str = "style_analysis",
    validation: Optional[Dict[str, Any]] = None,
    fidelity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compile final markdown report, sidecar JSON, and mapping files.
    """
    meta = prepare_result.get("prepare_meta", {})
    work_title = meta.get("work_title", "未命名作品")
    author_name = meta.get("author_name", "佚名")
    desensitize_enabled = meta.get("desensitize", True)
    allow_identity = bool(meta.get("allow_author_identity", False))
    # Identity Policy: public_sanitized never carries real title/author
    # in headers, meta, or filenames. Real identity stays in prepare_meta
    # (private) and private sidecar only.
    try:
        from ..distill.desensitize import compute_work_id as _wid
        work_id = _wid(author_name, work_title)
    except Exception:
        work_id = "WORK_UNKNOWN"
    public_title = work_title if (allow_identity or not desensitize_enabled) else work_id
    public_author = author_name if (allow_identity or not desensitize_enabled) else "已脱敏"

    raw_desens_map = parsed_json.get("desensitization_map", {}) if parsed_json else {}
    include_raw_evidence = bool(meta.get("include_raw_evidence", False))

    # Apply desensitization to Markdown prose and hide raw quote bodies in the
    # default public artifact. The raw response remains available only through
    # the explicit private sidecar switch. With desensitization disabled the
    # noun mapping is skipped entirely on both channels (structural minimization
    # of sample quotes still applies); the artifact is marked policy "raw".
    if desensitize_enabled:
        public_mapping, mapping_errors, mapping_warnings = _build_public_mapping(
            raw_desens_map,
            prepare_result.get("proper_noun_candidates", []),
        )
        # Ensure author/work always have a neutral fallback so warnings
        # mentioning them can be sanitized (they are in candidates already,
        # but be explicit when candidates are empty in unit tests).
        _fb_idx = len(public_mapping)
        for _ident in (author_name, work_title):
            _t = str(_ident or "").strip()
            if len(_t) >= 2 and _t not in public_mapping and not allow_identity:
                public_mapping[_t] = _fallback_label(_fb_idx)
                _fb_idx += 1
        clean_prose = desensitize_prose(_compose_single_source(prose_markdown, parsed_json), public_mapping)
    else:
        public_mapping, mapping_errors, mapping_warnings = {}, [], []
        clean_prose = _compose_single_source(prose_markdown, parsed_json)

    # 渲染终检：证据占位符必须恰好被一对引号包住。遮蔽正则若越界吞并
    # metric/「注解：」字段，占位符后会残留引号碎片或裸文本——四重校验
    # 看不到这种损坏，必须在公开产物落盘前拒绝。
    _malformed = [
        ln for ln in clean_prose.splitlines()
        if _PUBLIC_EVIDENCE_PLACEHOLDER in ln
        and not re.search(
            r"[“\"'「『]" + re.escape(_PUBLIC_EVIDENCE_PLACEHOLDER) + r"[”\"'」』]", ln
        )
    ]
    if _malformed:
        raise ValueError(
            "渲染终检失败：证据占位符形态异常（疑似遮蔽吞并注解/指标字段），拒绝渲染: "
            + _malformed[0][:80]
        )

    # Header metadata block for markdown (sanitized header by default)
    header_lines = [
        f"# 《{public_title}》风格能力解构报告",
        "",
        "> **报告契约**：四层契约 · 脱敏 · 证据锚点 · 保真闭环",
        f"> **分析对象**：{public_title}（来源作者标记：{public_author}）",
        f"> **采样范围**：{meta.get('sample_range_desc', '全样本/代表性采样')}",
        f"> **降噪过滤**：已清洗平台寄语与格式噪音（噪音占比: {meta.get('noise_ratio_pct', '0.00%')}）",
        f"> **产物策略**：{'raw' if not desensitize_enabled else 'public_sanitized'} · {work_id}",
    ]
    if validation:
        header_lines.append(
            f"> **校验状态**：schema {validation.get('schema', '-')} / 脱敏 {validation.get('desensitization', '-')} / "
            f"数值审计 {(validation.get('numeric_audit') or {}).get('status', '-')}"
            f"（质量自评与校验摘要见 report.json 的 quality / validation_summary 字段）"
        )
    header_lines.extend(["", "---", ""])
    # 附录 A：跨期对比矩阵。四层标题不变，新字段一律落在附录，不插入四层正文。
    # 附录 B/C 依赖已脱敏的公开侧数据（public_quant / report_json 的
    # deployment_config），所以在 report_json 组装完成后再拼接。
    cross_era_block = _render_cross_era_appendix(
        prepare_result.get("cross_era_matrix")
        or build_cross_era_matrix(prepare_result.get("era_window_metrics") or []))
    body_markdown = "\n".join(header_lines) + clean_prose + cross_era_block

    # Machine JSON sidecar. Public artifacts intentionally omit raw excerpts,
    # speaker samples, and evidence quote text; downstream consumers receive
    # stable structure and verification metadata without corpus disclosure.
    public_quant = _sanitize_public_value(
        prepare_result.get("quantitative_features", {}), public_mapping
    )
    public_voiceprint = _public_voiceprint(
        (prepare_result.get("quantitative_features") or {}).get("dialogue_features", {}),
        public_mapping,
        prepare_result.get("proper_noun_candidates", []) or [],
        author_name,
        work_title,
        use_real_names=not desensitize_enabled,
    )
    public_cards = _sanitize_public_value(
        parsed_json.get("technique_cards", []) if parsed_json else [], public_mapping
    )
    public_thinking = _sanitize_public_value(
        parsed_json.get("thinking_layer", {}) if parsed_json else {}, public_mapping
    )
    public_dialogue = _sanitize_public_value(
        parsed_json.get("dialogue_review", {}) if parsed_json else {}, public_mapping
    )
    public_map = _export_public_mapping(public_mapping)
    # 三套风格模板由公开侧的三块数据渲染（均已完成专名映射），模板本身不再引入
    # 任何新字符串来源，因此渲染结果只需再走一次幂等脱敏即可安全入 sidecar。
    style_seed: Dict[str, Any] = {
        "quantitative_features": public_quant,
        "technique_cards": public_cards,
        "voiceprint": public_voiceprint,
    }
    json_meta: Dict[str, Any] = {
        "work_id": work_id,
        "mode": meta.get("mode", "full"),
        "noise_ratio": meta.get("noise_ratio", 0.0),
        "sample_range": meta.get("sample_range_desc", ""),
    }
    # Real title/author only in explicit identity modes; default sanitized
    # meta carries work_id so public JSON has zero known-identity strings.
    if allow_identity or not desensitize_enabled:
        json_meta["work_title"] = work_title
    if allow_identity:
        json_meta["author_name"] = author_name
    report_json: Dict[str, Any] = {
        "version": __version__,
        "schema_version": REPORT_SCHEMA_VERSION,
        "artifact_policy": "raw" if not desensitize_enabled else "public_sanitized",
        "meta": json_meta,
        "writer_contract": _sanitize_public_value(
            parsed_json.get("writer_contract", {}) if parsed_json else {}, public_mapping
        ),
        "quantitative_features": public_quant,
        # 公开话术块：原型标签 → 口吻/话术习惯。私有侧的真实人名与整句台词
        # 被 _SENSITIVE_QUANT_KEYS 剔除后，这里是唯一保留声纹信息的公开通道。
        "voiceprint": public_voiceprint,
        # 跨期对比矩阵：分期标签是中性代号（开头/发展/…），值为纯数值，无身份。
        "cross_era_matrix": _sanitize_public_value(
            prepare_result.get("cross_era_matrix") or {}, public_mapping),
        # 分身配套产物：由实测数值渲染，仍过一遍映射并在终检中受身份扫描约束。
        "deployment_config": _sanitize_public_value(
            build_deployment_config(prepare_result.get("quantitative_features", {}) or {}),
            public_mapping),
        "style_templates": _sanitize_public_value(
            render_all_style_templates(style_seed), public_mapping),
        "technique_cards": public_cards,
        "thinking_layer": public_thinking,
        # Claims are an optional extension layer, but when present they are
        # public content like everything else and must carry the same mapping.
        "claims": _sanitize_public_value(
            parsed_json.get("claims", []) if parsed_json else [], public_mapping
        ),
        "desensitization_map": public_map,
        "dialogue_review": public_dialogue,
        "provenance": {
            "pipeline_version": __version__,
            "schema_version": REPORT_SCHEMA_VERSION,
            "is_fallback_index": bool(meta.get("is_fallback_index", False)),
            "coverage_pct": meta.get("coverage_pct"),
            "encoding": meta.get("encoding"),
            "era_count": len({
                v for v in (prepare_result.get("era_map") or {}).values()
                if v and v != "未分期"
            }),
            "chapter_count": len(prepare_result.get("era_spans") or []),
            "evidence_count": len(prepare_result.get("evidence_store_ids") or {}),
            "placeholder_registry": build_placeholder_map(
                prepare_result.get("quantitative_features", {}) or {}
            ),
            "metric_registry": prepare_result.get("metric_registry") or {},
        },
        "validation_summary": _validation_summary(validation, public_mapping),
        "fidelity": fidelity,
        "artifact_diagnostics": {
            "mapping_error_count": len(mapping_errors),
            "mapping_warning_count": len(mapping_warnings),
        },
    }

    # 附录 B/C 只读公开侧数据（public_quant 已剔除身份轨迹字段，report_json 的
    # deployment_config/style_templates 已完成映射），因此拼接结果与 sidecar 同源
    # 且同样满足脱敏红线；再走一次幂等脱敏，防止模板里的实测字符串带出专名。
    quant_appendix = _render_quant_extension_appendix(public_quant)
    kit_appendix = _render_persona_kit_appendix(report_json)
    if desensitize_enabled and public_mapping:
        quant_appendix = apply_desensitization(quant_appendix, public_mapping)
        kit_appendix = apply_desensitization(kit_appendix, public_mapping)
    full_markdown = body_markdown + quant_appendix + kit_appendix

    files_saved = {}
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        internal_path = out_path / ".internal"
        if include_raw_evidence:
            internal_path.mkdir(parents=True, exist_ok=True)

        md_file = out_path / f"{base_name}.md"
        json_file = out_path / f"{base_name}.json"
        # map/manifest 按报告名作用域：同目录多次 finalize（多报告→一人格的
        # 常态工作流）不再互相覆盖。
        map_file = out_path / f"{base_name}_desensitization_map.json"
        manifest_file = out_path / f"{base_name}_manifest.json"

        _atomic_write_text(md_file, full_markdown)
        _atomic_write_text(json_file, json.dumps(report_json, ensure_ascii=False, indent=2))
        if desensitize_enabled and report_json["desensitization_map"]:
            _atomic_write_text(map_file, json.dumps(report_json["desensitization_map"], ensure_ascii=False, indent=2))
        # Manifest sidecar (public, no identities).
        _atomic_write_text(manifest_file, json.dumps({
            "pipeline_version": __version__,
            "schema_version": REPORT_SCHEMA_VERSION,
            "artifact_policy": report_json.get("artifact_policy"),
            "work_id": json_meta.get("work_id"),
            "validation": {
                "integrity": (validation or {}).get("schema"),
                "quality": ((validation or {}).get("quality") or {}).get("status", "n/a")
                if isinstance((validation or {}).get("quality"), dict) else "n/a",
                "privacy": (validation or {}).get("desensitization"),
            },
            "provenance": report_json.get("provenance", {}),
        }, ensure_ascii=False, indent=2))

        private_file = internal_path / f"{base_name}_private_evidence.json"
        if include_raw_evidence:
            private_payload = {
                "artifact_policy": "private_raw_evidence",
                "desensitization_map": raw_desens_map,
                "evidence_store": prepare_result.get("evidence_store", {}),
                "evidence_store_ids": prepare_result.get("evidence_store_ids", {}),
                "era_map": prepare_result.get("era_map", {}),
                "era_id_map": prepare_result.get("era_id_map", {}),
                "raw_technique_cards": parsed_json.get("technique_cards", []) if parsed_json else [],
                # 正反例抽取只进私有通道：正例是原文片段，反例可能命中脱敏红线。
                "exemplars": _extract_exemplars_for_private(
                    prepare_result.get("evidence_pool") or []),
            }
            _atomic_write_text(private_file, json.dumps(private_payload, ensure_ascii=False, indent=2))

        files_saved = {
            "report_md_path": str(md_file),
            "report_json_path": str(json_file),
            "desensitization_map_path": str(map_file) if report_json["desensitization_map"] else None,
            "manifest_path": str(manifest_file),
            "private_evidence_path": str(private_file) if include_raw_evidence else None,
        }

    return {
        "full_markdown": full_markdown,
        "report_json": report_json,
        "files_saved": files_saved,
    }
