# -*- coding: utf-8 -*-
"""Shared fixtures: synthetic corpus, prepared stage output, LLM responses.

Everything here is deterministic (fixed seeds, no network, no clock) so the
whole suite can assert on exact numbers where that matters.
"""
from __future__ import annotations

import json
import random
import re
from typing import Any, Callable, Dict, List, Optional

from author_persona_skill import prepare_analysis
from author_persona_skill.report.renderer import extract_json_block

# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------

_NAMES = ("林砚", "苏疏", "陆沉", "裴无咎", "沈九娘", "顾长风")
_TAGS = ("说道", "问道", "答道", "笑道", "摇头", "点头", "皱眉")
_OBJECTS = ("长剑", "铜铃", "残卷", "药炉", "山门", "石阶", "断崖", "古井")
_SCENERY = ("晨雾未散", "暮色四合", "雨声淅沥", "风声骤起", "灯火将熄")
_LINES = ("走吧", "当真", "为何", "不可", "且慢", "原来如此", "你先说", "我明白了")
_REPLIES = ("此事另有蹊跷", "山下的路断了", "我等你三日", "不要再问", "就此别过")


def _sentence(rng: random.Random) -> str:
    name = rng.choice(_NAMES)
    obj = rng.choice(_OBJECTS)
    scene = rng.choice(_SCENERY)
    roll = rng.random()
    if roll < 0.30:
        return (f"“{rng.choice(_LINES)}，”{name}{rng.choice(_TAGS)}，"
                f"“{rng.choice(_REPLIES)}。”")
    if roll < 0.50:
        return f"{scene}，{name}握紧了{obj}，一步踏出，石屑簌簌落下。"
    if roll < 0.60:
        return "他像是被什么攫住了——那是一种说不清的预感。"
    if roll < 0.70:
        return f"{obj}上的纹路宛如蛇行，久久不曾散去，仿佛在等一个答案。"
    if roll < 0.80:
        return f"“{rng.choice(('难道', '岂能', '莫非', '何必'))}{rng.choice(('如此', '罢了', '当真', '不成'))}？”{name}低声道。"
    if roll < 0.88:
        return f"他想着{obj}，又想着山门前的雨，心里一阵发凉。"
    return f"{scene}。{name}立在{obj}前，久久不动。"


def synthetic_corpus(chapters: int = 20, seed: int = 7) -> str:
    """A deterministic Chinese novel-shaped corpus with chapters and noise."""
    rng = random.Random(seed)
    buf: List[str] = []
    for chapter in range(1, chapters + 1):
        buf.append(f"第{chapter}章 山门夜雨\n\n")
        for _ in range(9):
            buf.append("".join(_sentence(rng) for _ in range(rng.randint(2, 5))) + "\n\n")
        buf.append("***\n\n")
        buf.append("感谢书友的打赏，求月票！\n\n")
    return "".join(buf)


# --------------------------------------------------------------------------
# prepare_analysis output (cached: the pipeline is deterministic)
# --------------------------------------------------------------------------

_PREPARE_CACHE: Dict[str, Dict[str, Any]] = {}


def prepared(
    key: str = "default",
    *,
    chapters: int = 20,
    author: str = "测试作者",
    title: str = "测试书",
    budget: int = 30000,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """prepare_analysis on the synthetic corpus, memoised per *inputs*.

    The cache key is the real corpus configuration, not the caller's label: the
    low-level layer tokenizes the whole corpus with jieba, and keying on a free-form
    label made every ``key="xxx"`` call re-run the full pipeline on an identical
    corpus (nine times in the current suite).
    """
    cache_key = f"{chapters}|{author}|{title}|{budget}|{sorted((options or {}).items())}"
    if cache_key not in _PREPARE_CACHE:
        opts = {"sample_budget_chars": budget}
        opts.update(options or {})
        _PREPARE_CACHE[cache_key] = prepare_analysis(
            corpus_text=synthetic_corpus(chapters=chapters),
            author_name=author,
            work_title=title,
            options=opts,
        )
    return _PREPARE_CACHE[cache_key]


# --------------------------------------------------------------------------
# A validation-passing LLM response
# --------------------------------------------------------------------------

_EVIDENCE_METRIC = {
    "metaphor_anchor": "比喻密度",
    "dash_anchor": "破折号",
    "ellipsis_anchor": "省略号",
    "dialogue_tag_anchor": "对话占比",
    "short_para_anchor": "极短段率",
    "exemplification_anchor": "比喻密度",
}

_LONG_SECTIONS = {
    "1.1": ("样本规模构成的第一印象是“短促而密集”：总字符 {{total_chars}} 字分布在 "
            "{{total_paragraphs}} 段中，有效句子 {{total_sentences}} 句，全书降噪占比 "
            "{{noise_ratio_pct}}。这三个数并列后指向一个基本判断——样本属于高密度短章推进的"
            "连载体，段落多、句子碎，单段承载的信息量被刻意压到最低，读者的阅读节奏因此"
            "始终保持在“翻页”状态。"),
    "1.2": ("平均句长 {{avg_sent_len}} 字与中位 {{median_sent_len}} 字高度接近，说明句长分布"
            "没有长尾拖拽；短句率 {{short_sent_ratio_pct}} 与长句率 {{long_sent_ratio_pct}} 的"
            "悬殊对比是本节最鲜明的矛盾信号，分档落在 {{sent_len_bracket}}。短句承担推进、"
            "长句仅用于少数信息压缩场合，两者共振出一种“碎步快走”的行文呼吸。"),
    "1.3": ("平均段长 {{avg_para_len}} 字配合极短段率 {{short_para_ratio_pct}}，构成典型的"
            "单句成段节奏；场景切换密度 {{scene_switch_density}} 次/千字意味着换场并不频繁，"
            "节奏靠段落内部的短句脉冲而非场景跳跃维持，读者被留在同一时空里反复被短句推动。"),
    "1.4": ("对话字符占比 {{dialogue_ratio_pct}}，道:说比 {{dao_shuo_ratio}}，标签分布高度集中"
            "于少数几个动词。这一组合说明对白是任务驱动的：引语只承担信息交换与立场表态，"
            "闲聊被压缩到最低，互动驱动力来自“每句话都有目的”的紧张感。"),
    "1.5": ("逗号密度 {{punc_comma}} 与句号密度 {{punc_period}} 决定了逗句比 "
            "{{comma_period_ratio}}；省略号 {{punc_ellipsis}}、破折号 {{punc_dash}} 的密度"
            "共同标定情绪外放度。逗号管推进、句号管收束，二者的比例关系说明作者更依赖短句"
            "收束而非长句铺陈，情绪靠停顿而不是靠标点爆发。"),
    "1.6": ("比喻密度 {{metaphor_density}}、反问密度 {{rhetorical_question_density}}、排比密度 "
            "{{parallelism_density}} 三者构成修辞引擎的配比。比喻以单句点染为主、极少铺陈，"
            "反问用于代替心理独白，排比近乎缺席——修辞在这里是功能性的，不是装饰性的。"),
    "1.7": ("第三人称计数 {{third_person_count}} 次对第一人称 {{first_person_count}} 次，差距"
            "悬殊，说明镜头紧贴主角行动的限知视角；镜头距离在动作与物象之间快速推拉，很少"
            "做全景俯瞰，读者始终与主角保持同一视野。"),
    "1.8": ("动作主导句 {{action_count}}、心理 {{mental_count}}、环境 {{env_count}}，动作心理比 "
            "{{action_mental_ratio}}，驱动模式 {{driver_mode}}。这一配比意味着人物状态几乎全部"
            "通过外部行动外化，心理描写只在动作之后短暂停留，形成“外部行动→内部反应”的节拍链。"),
    "1.9": ("高置信声纹集中在少数原型角色上：主角原型口吻简短、以判断句推进，平均句长明显低于"
            "全篇均值；对手原型语气试探、善用反问，把压迫感放进疑问句里。两者的共同规则是标签"
            "只承担归属，情绪全部由引语内容承载，因此模仿时必须先定引语的信息量，再选标签；"
            "若标签承担了情绪，声纹就会立刻塌陷成通用腔调。"),
    "1.10": ("高频意象集中在天气、器物与山野三类，属于可迁移的意象类型而非专有设定；词汇层面"
             "依赖具象名词与短促动词，抽象概念极少直接出现。这意味着该风格的世界观呈现方式"
             "是“从物象进入”，而不是先立设定再描写，模仿时需要先给一个可见的物，再让意义从"
             "物上长出来。"),
    "1.11": ("1. 短句脉冲推进（短句率 {{short_sent_ratio_pct}}，句长中位数 {{median_sent_len}} 字）\n"
             "2. 具象比喻单句收束（比喻密度 {{metaphor_density}}）\n"
             "3. 单极对话标签（道:说比 {{dao_shuo_ratio}}）\n"
             "4. 短段换行呼吸（极短段率 {{short_para_ratio_pct}}）"),
}


def _evidence_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "evidence_id": item["evidence_id"],
        "chunk_id": item["chunk_id"],
        "quote": item["quote"],
        "metric": _EVIDENCE_METRIC.get(item["type"], "比喻密度"),
        "note": f"该句以{item['type']}的形式体现本卡机制。",
    }


def _cross_era_pair(pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for index, left in enumerate(pool):
        for right in pool[index + 1:]:
            if left.get("era") and right.get("era") and left["era"] != right["era"]:
                return [left, right]
    return [pool[0], pool[1 % len(pool)]]


def valid_response(prep: Dict[str, Any]) -> str:
    """A response that passes every gate (structure/schema/evidence/privacy/numeric)."""
    pool = list(prep["evidence_pool"])
    pair = _cross_era_pair(pool)

    def pick(kind: str) -> Dict[str, Any]:
        for item in pool:
            if item["type"] == kind:
                return item
        return pool[0]

    cards = [
        {
            "id": "T01",
            "name": "跨期比喻点染收束",
            "definition": "在段落收束处用单句比喻把抽象状态转译为具象画面，句子以喻词连接本体与喻体，不再延展为独立描写段。",
            "serves_purpose": "让读者在段落收尾处获得一次具象化的画面定格",
            "trigger": "段落需要一个可见画面收束情绪时",
            "steps": ["定位句中已出现的具体物象", "用喻词把本体映射到具象喻体", "单句内完成映射并立即收束，不另起描写段"],
            "boundary": "高速动作段禁用（比喻会拖慢节拍）；连续使用会让读者审美疲劳，需间隔若干段再出现。",
            "counterexample": "未发现明确反例",
            "evidence": [_evidence_item(pair[0]), _evidence_item(pair[1])],
            "transferability": "high",
            "confidence": "high",
        },
        {
            "id": "T02",
            "name": "对话标签单极化",
            "definition": "全篇以单一言语标签承担对白引导，情绪不由标签修饰而由引语内容承载，标签只负责归属说话人。",
            "serves_purpose": "让多轮交锋的对白紧凑连贯，读者不因修饰性标签出戏",
            "trigger": "两人及以上连续交锋时",
            "steps": ["对话只使用主力标签与疑问标签两类", "情绪改由引语内部的信息与停顿表达", "动作从标签中剥离、独立成段"],
            "boundary": "群口混战禁用（归属会混乱）；单一标签连用过长会让读者失去声纹辨识度，需要靠引语内容区分。",
            "counterexample": "未发现明确反例",
            "evidence": [_evidence_item(pick("dialogue_tag_anchor")), _evidence_item(pool[0])],
            "transferability": "high",
            "confidence": "high",
        },
        {
            "id": "T03",
            "name": "破折号揭底插入",
            "definition": "在叙述中途以破折号插入补充说明或自我修正，使信息分层释放，读者在句中完成一次认知补全。",
            "serves_purpose": "把一次关键信息的分层揭示压缩进同一句，维持行文推进感",
            "trigger": "需要补充一个与当前句紧密相关的事实或修正时",
            "steps": ["在需要补充处插入破折号而非另起一句", "插入内容只承载一个信息点", "插入后立刻回到原句主干收束"],
            "boundary": "连续成对插入语滥用会让句子失焦；同一段超过两处应改为分句陈述。",
            "counterexample": "未发现明确反例",
            "evidence": [_evidence_item(pick("dash_anchor")), _evidence_item(pick("ellipsis_anchor"))],
            "transferability": "mid",
            "confidence": "high",
        },
    ]

    payload = {
        "writer_contract": {
            "positioning": "架空武侠连载样本，面向中长篇连载读者",
            "purpose": "读者每章至少获得一次危机推进与一次具象画面定格",
            "style_marks_synthesis": "短句推进、具象比喻收束与单极对话标签三者交替，形成压迫—定格的阅读律动",
            "enemy_clauses": ["严禁修饰性对话标签堆叠", "严禁连续三段无场景切换", "严禁解释性副词拖慢动作节拍"],
        },
        "technique_cards": cards,
        "thinking_layer": {
            "attention_order": "进入场景先看见物象与天气，再看见人物动作与关系。",
            "info_control": "关键信息分层释放，先给断裂表象再给完整因果。",
            "conflict_escalation": "压力阶梯式加码，每次化解旧冲突都引出更高维度危机。",
            "cost_management": "胜利伴随不可逆代价，避免零代价爽感。",
            "closure": "场景以未定态画面收束，保持翻页钩子。",
            "long_arc": (f"早期锚点 [{pair[0]['chunk_id']}] 与后期锚点 [{pair[1]['chunk_id']}] "
                         f"显示同一机制贯穿全书。"),
            "adaptation_boundary": "适合快节奏冒险与危机推进题材，不适合慢热日常与细腻心理独白。",
        },
        "desensitization_map": _archetype_map(prep),
        # 角色话术复盘必须由实测说话人支撑：语料的高置信角色各确认一个原型。
        # role 只允许用映射给出的原型标签，不能回填原角色名。
        "dialogue_review": {
            "confirmed_profiles": [
                {"role": "原型丙", "tone": "陈述型，起句多用「当真」「且慢」",
                 "sample_tag": "道"},
                {"role": "原型丁", "tone": "陈述型，常以「不可」开头",
                 "sample_tag": "笑道"},
            ],
            "discarded_candidates": [],
        },
    }

    prose = ["## 第〇部分：作家定义与读者契约（作家契约层）", "", "## 第一部分：定量风格分析报告（定量层）", ""]
    for number in range(1, 12):
        prose.append(f"### 1.{number} 小节标题")
        prose.append(_LONG_SECTIONS[f"1.{number}"])
        prose.append("")
    prose += [
        "## 第二部分：核心写作技法提取（技法调用卡层）",
        "",
        "## 第三部分：作家创作思维与宏观心智（思维层）",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return "\n".join(prose)


def _archetype_map(prep: Dict[str, Any]) -> Dict[str, str]:
    labels = ("原型甲", "原型乙", "原型丙", "原型丁")
    mapping: Dict[str, str] = {}
    for index, candidate in enumerate(prep.get("proper_noun_candidates", [])):
        term = str(candidate.get("term", "")).strip()
        if len(term) >= 2 and term not in mapping:
            mapping[term] = labels[len(mapping) % len(labels)]
    return mapping


# --------------------------------------------------------------------------
# Response surgery helpers
# --------------------------------------------------------------------------

def mutate_json(response: str, mutate: Callable[[Dict[str, Any]], None]) -> str:
    """Apply ``mutate`` to the trailing JSON block and rebuild the response."""
    prose, data = extract_json_block(response)
    assert data is not None, "fixture response has no JSON block"
    mutate(data)
    return prose + "\n\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```\n"


def drop_heading(response: str, heading: str) -> str:
    """Remove a line-level ``##`` heading (simulates a malformed response)."""
    return re.sub(rf"^##[^\n]*{re.escape(heading)}[^\n]*\n", "", response, flags=re.M)


def scene_block(label: str, filler: str = "山风掠过石阶，林砚按住剑柄，听见远处传来一声闷响。") -> str:
    """A single trial-writing scene of >=800 chars with an optional type label."""
    body = (f"{label}\n" if label else "") + (filler * 35) + "\n"
    return body


def trial_text(scenes: Optional[List[str]] = None) -> str:
    """A 3-scene trial text that satisfies the fidelity scene contract."""
    parts = scenes or [scene_block("日常"), scene_block("冲突"), scene_block("抉择")]
    return "\n\n---\n\n".join(parts)
