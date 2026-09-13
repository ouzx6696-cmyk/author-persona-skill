# -*- coding: utf-8 -*-
"""Command-line interface for author-persona-skill."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure package parent directory is in sys.path when executed directly
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from author_persona_skill import __version__  # single source: pyproject.toml
from author_persona_skill.pipeline import (
    prepare_analysis,
    finalize_analysis,
    analyze_style,
    process_large_file,
)
from author_persona_skill.fidelity.fidelity_check import run_fidelity_check
from author_persona_skill.corpus.file_processor import read_text_file


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="author-persona-skill",
        description=f"作家分身技能 v{__version__} CLI (四层契约 · 脱敏 · 证据锚点 · 保真闭环)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # 1. prepare
    p_prepare = subparsers.add_parser("prepare", help="阶段一：计算定量特征并生成 LLM Prompt 与证据锚点")
    p_prepare.add_argument("corpus", help="小说语料文件路径 (.txt)")
    p_prepare.add_argument("--author", default="", help="原作者姓名（仅用于元信息与脱敏检测）")
    p_prepare.add_argument("--title", default="", help="作品标题")
    p_prepare.add_argument("--budget", type=int, default=150000,
                           help="采样预算（软目标：受「每时期至少保留 2 章」硬下限约束，实际采样可能超出，默认: 150000）")
    p_prepare.add_argument("--generate-system-prompt", action="store_true",
                           help="标记本次分析需生成作家分身系统提示词（由 finalize 阶段产出）")
    p_prepare.add_argument("--allow-author-identity", action="store_true",
                           help="允许分身提示词署名来源作者（默认脱敏为风格载体型）")
    p_prepare.add_argument("--no-desensitize", action="store_true", help="关闭脱敏校验（默认开启）")
    p_prepare.add_argument("--include-raw-evidence", action="store_true",
                           help="额外输出含原文证据的私有 sidecar（不可公开）")
    p_prepare.add_argument("--output-json", help="保存 prepare 结果中间 JSON 文件路径")
    p_prepare.add_argument("--output-prompt", help="保存 LLM Prompt 的文本文件路径")

    # 2. finalize
    p_finalize = subparsers.add_parser("finalize", help="阶段三：解析 LLM 响应，执行校验并渲染报告与 report.json")
    p_finalize.add_argument("--prepare-json", required=True, help="阶段一生成的 prepare 结果 JSON 路径")
    p_finalize.add_argument("--response-file", required=True, help="LLM 响应文本文件路径")
    p_finalize.add_argument("--output-dir", default=".", help="输出报告与机器数据目录")
    p_finalize.add_argument("--base-name", help="输出报告基础文件名")
    p_finalize.add_argument("--trial-file", help="可选：试写文本路径，触发保真闭环并写入报告附录")
    p_finalize.add_argument("--repair-prompt-out",
                            help="可选：校验失败时把修复提示词写入该文件（同一会话内追加即可重试）")

    # 3. analyze
    p_analyze = subparsers.add_parser("analyze", help="纯定量风格指标测量")
    p_analyze.add_argument("corpus", help="小说语料文件路径")
    p_analyze.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    # 4. plan
    p_plan = subparsers.add_parser("plan", help="建立章节索引与五时期阅读计划")
    p_plan.add_argument("corpus", help="小说语料文件路径")
    p_plan.add_argument("--budget", type=int, default=150000, help="采样预算")

    # 5. fidelity
    p_fidelity = subparsers.add_parser("fidelity", help="保真度闭环校验")
    p_fidelity.add_argument("--trial", required=True, help="试写文本文件路径")
    p_fidelity.add_argument("--report-json", required=True, help="已生成的 report.json 路径")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        return _main_command(args)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"author-persona-skill: error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - stable CLI error contract
        print(f"author-persona-skill: internal error: {exc}", file=sys.stderr)
        return 3


def _main_command(args) -> int:
    if args.command == "prepare":
        res = prepare_analysis(
            corpus_path=args.corpus,
            author_name=args.author,
            work_title=args.title,
            options={
                "sample_budget_chars": args.budget,
                "include_raw_evidence": getattr(args, "include_raw_evidence", False),
                "generate_system_prompt": getattr(args, "generate_system_prompt", False),
                "allow_author_identity": getattr(args, "allow_author_identity", False),
                "desensitize": not getattr(args, "no_desensitize", False),
            },
        )
        _sampled = ((res.get("quantitative_features") or {}).get("text_summary") or {}).get("total_chars")
        if isinstance(_sampled, int) and args.budget > 0:
            _ratio = _sampled / args.budget
            print(f"[i] 采样量/预算: {_sampled:,}/{args.budget:,} = {_ratio:.2f} 倍"
                  f"（--budget 为软目标，每时期至少保留 2 章的硬下限优先）")
            if _ratio > 1.5:
                print("[!] 实际采样超出预算 1.5 倍：小语料受每时期硬下限保护而超采属正常；"
                      "如需严格控量请提高 --budget 或改用 analyze 子命令。")
        if args.output_prompt:
            prompt_path = Path(args.output_prompt)
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            # system 消息随 prompt.txt 头部输出一行，
            # 纯 CLI 工作流的用户不必反序列化中间产物才能拿到它。
            _sys = res.get("llm_system_msg") or ""
            prompt_path.write_text(
                (f"<!-- SYSTEM: {_sys} -->\n\n" if _sys else "") + res["llm_prompt"],
                encoding="utf-8",
            )
            print(f"[OK] Prompt 已输出至: {args.output_prompt}")
        if args.output_json:
            output_path = Path(args.output_json)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[OK] Prepare 结果已保存至: {args.output_json}")
            print("[!] 注意：prepare JSON 含原文证据（evidence_store），仅限私有保存，禁止公开分发。")
        if not args.output_prompt and not args.output_json:
            print(res["llm_prompt"])

    elif args.command == "finalize":
        prep_data = json.loads(Path(args.prepare_json).read_text(encoding="utf-8"))
        resp_text, _ = read_text_file(args.response_file)
        trial_text = None
        if getattr(args, "trial_file", None):
            trial_text, _ = read_text_file(args.trial_file)
        res = finalize_analysis(
            prepare_result=prep_data,
            llm_response=resp_text,
            output_dir=args.output_dir,
            base_name=args.base_name,
            trial_text=trial_text,
        )
        # On rejection the repair prompt is the actionable next step; persist it
        # when asked so the retry does not depend on reading stdout.
        repair_prompt = (res.get("validation") or {}).get("repair_prompt")
        if repair_prompt and getattr(args, "repair_prompt_out", None):
            repair_path = Path(args.repair_prompt_out)
            repair_path.parent.mkdir(parents=True, exist_ok=True)
            repair_path.write_text(repair_prompt, encoding="utf-8")
            print(f"[OK] 修复提示词已输出至: {args.repair_prompt_out}")

        if res["status"] != "passed":
            # Two distinct failure modes must not be conflated:
            #   (a) validation failed  -> nothing rendered, only *_rejected.md
            #   (b) validation passed but the fidelity loop did not -> the report
            #       WAS rendered and saved, with the deviation table in its appendix.
            fidelity = res.get("fidelity")
            if res["validation"].get("status") != "passed" or fidelity is None:
                print("[X] 响应未通过校验，已拒绝渲染正式报告。")
                for err in res["validation"].get("errors", []):
                    print(f"    - {err}")
                print(f"    - 拒绝产物: {res.get('rejected_path')}")
                if repair_prompt:
                    print("    - 修复提示词: validation.repair_prompt（或用 --repair-prompt-out 导出）")
                return 1
            print(f"[!] 报告校验已通过并落盘，但保真闭环未达标（fidelity: {fidelity.get('status')}）。")
            print(f"    - Markdown 报告: {res.get('report_path')}")
            print(f"    - JSON Sidecar: {res.get('report_json_path')}")
            for reason in fidelity.get("overall_reasons", [])[:5]:
                print(f"    - {reason}")
            print("    - 偏差对比表已写入报告附录；修正试写后可用 fidelity 子命令单独复核")
            return 1
        print(f"[OK] 报告处理完成，状态: {res['status']}")
        print(f"    - Markdown 报告: {res.get('report_path')}")
        print(f"    - JSON Sidecar: {res.get('report_json_path')}")
        if res.get("report_json", {}).get("artifact_policy"):
            print(f"    - Artifact policy: {res['report_json']['artifact_policy']}")
        _pub = (res.get("validation") or {}).get("publishable")
        if _pub:
            # publishable=failed 不阻断（软质量闸是设计取舍），但 [OK] 后
            # 必须让降级原因可见，不能让读者误以为产物已满格可发布。
            if _pub == "failed":
                _q = (res.get("validation") or {}).get("quality") or {}
                print(f"[OK] status=passed / quality=publishable:{_pub}")
                for reason in (_q.get("reasons") or [])[:5]:
                    print(f"    - publishable 降级原因: {reason}")
            else:
                print(f"    - Publishable (integrity/quality/privacy): {_pub}")
        if res.get("report_json", {}).get("meta", {}).get("work_id"):
            print(f"    - Work ID: {res['report_json']['meta']['work_id']}")

        for warn in res["validation"].get("warnings", [])[:5]:
            print(f"    [warn] {warn}")

    elif args.command == "analyze":
        text, _ = read_text_file(args.corpus)
        res = analyze_style(text)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            summary = res.get("text_summary", {})
            sent = res.get("sentence_structure", {})
            diag = res.get("dialogue_features", {})
            print(f"=== 《{Path(args.corpus).stem}》定量分析概览 ===")
            print(f"- 总字符: {summary.get('total_chars'):,}（噪音过滤: {summary.get('noise_ratio_pct')}）")
            print(f"- 平均句长: {sent.get('avg_sent_len')} 字（短句率: {sent.get('short_sent_ratio_pct')}）")
            print(f"- 对话字符占比: {diag.get('dialogue_ratio_pct')}（道:说比 {diag.get('dao_shuo_ratio')}）")
            print(f"- 核心风格标记: {' | '.join(res.get('style_markers', []))}")

    elif args.command == "plan":
        plan_res = process_large_file(args.corpus, budget_chars=args.budget)
        plan = plan_res["reading_plan"]
        print(f"=== 《{Path(args.corpus).stem}》章节索引与阅读计划 ===")
        print(f"- 总章节数: {plan_res['total_chapters']}")
        print(f"- 噪音过滤: {plan_res.get('noise_ratio_pct', '0.00%')}")
        print(f"- 采样描述: {plan['sample_range_desc']}")
        for era, desc in plan.get("era_coverage", {}).items():
            print(f"  * {era}: {desc}")

    elif args.command == "fidelity":
        trial_text, _ = read_text_file(args.trial)
        report_json = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
        res = run_fidelity_check(
            trial_text=trial_text,
            reference_metrics=report_json.get("quantitative_features", {}),
            technique_cards=report_json.get("technique_cards", []),
        )
        print(f"=== 保真度闭环校验结果: {res['status'].upper()} ===")
        if not (res.get("copy_check") or {}).get("is_copy_risk", False) and \
                "跳过" in str((res.get("copy_check") or {}).get("reason", "")):
            print("[!] 复制检测已跳过（未提供参照文本）")
        for issue in (res.get("scene_requirements") or {}).get("issues", []):
            print(f"[!] 场景要求：{issue}")
        print("| 指标 | 参考基准 | 试写实测 | 偏差 | 容差阈值 | 状态 |")
        print("|---|---|---|---|---|---|")
        for d in res["deviations_table"]:
            print(f"| {d['metric']} | {d['reference']} | {d['trial']} | {d['deviation']} | {d['threshold']} | {d['status']} |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
