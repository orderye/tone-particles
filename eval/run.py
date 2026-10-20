#!/usr/bin/env python3
"""评测入口。

用法：
    python3 eval/run.py                          # 只跑确定性指标
    python3 eval/run.py --backend chat_completions   # 加上模型评审的三项
    python3 eval/run.py --generate --backend chat_completions   # 先生成回复再评测
    python3 eval/run.py --out eval/report.md     # 写出报告

确定性指标（助词密度、硬规则、颜文字、场景自适应、安全红队、随机）不调用任何
模型，读的是 eval/fixtures/responses/ 里的回复文件。需要模型的三项（风格盲测、
内容保真、融合识别）在没有可用后端时标记为「未评测」，不影响其余指标。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from backends import get_backend  # noqa: E402
from judge import blind, density, fidelity, fusion, kaomoji, random_mode, redteam, rules, scene  # noqa: E402
from judge.common import load_cases, load_responses  # noqa: E402
import generate as generator  # noqa: E402
import report as reporter  # noqa: E402

RESPONSES_DIR = EVAL_ROOT / "fixtures" / "responses"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="语气助词 Skill 评测")
    parser.add_argument("--responses", help="回复目录，默认 eval/fixtures/responses")
    parser.add_argument("--backend", default="none",
                        help="评审后端：none / fixture / chat_completions / messages_api / manual")
    parser.add_argument("--kaomoji", choices=["off", "on", "both"], default="both",
                        help="颜文字开关的判定方式，默认两态都跑")
    parser.add_argument("--generate", action="store_true", help="先生成缺失的回复")
    parser.add_argument("--overwrite", action="store_true", help="生成时覆盖已有回复")
    parser.add_argument("--density", default="standard", choices=["light", "standard", "strong"],
                        help="生成回复时使用的密度档位")
    parser.add_argument("--runs", type=int, default=1000, help="随机模式的模拟次数")
    parser.add_argument("--out", help="报告输出路径（同时写出 .json）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args(argv)

    responses_dir = Path(args.responses) if args.responses else RESPONSES_DIR
    chats = load_cases("chats")
    blind_cases = load_cases("blind")
    redteam_cases = load_cases("redteam")
    scene_cases = load_cases("scenes")
    fusion_cases = load_cases("fusion")
    case_sets = [chats, blind_cases, redteam_cases, scene_cases, fusion_cases]

    backend = get_backend(args.backend)
    backend_ok, backend_reason = backend.available()

    if args.generate:
        if not backend_ok:
            raise SystemExit(f"生成需要可用的后端，当前不可用：{backend_reason}")
        print("生成回复中……")
        stats = generator.generate_all(
            backend, case_sets, responses_dir,
            density_level=args.density,
            only_missing=not args.overwrite,
        )
        print(f"  新生成 {stats['generated']} 条，跳过已有 {stats['skipped']} 条，"
              f"失败 {stats['failed']} 条。")

    responses = load_responses(responses_dir)

    metrics = []

    # 确定性指标
    metrics.append(density.judge(responses, chats))
    metrics.append(rules.judge(responses, chats))
    metrics.append(kaomoji.judge(responses, chats, kaomoji_enabled=False))
    if args.kaomoji in ("on", "both"):
        metrics.append(kaomoji.judge(responses, chats, kaomoji_enabled=True))
        metrics.append(kaomoji.frequency(chats, responses, kaomoji_enabled=True))
    metrics.append(scene.judge(responses, scene_cases))
    metrics.append(redteam.judge(responses, redteam_cases))
    metrics.append(random_mode.judge(args.runs))

    # 需要评审模型的三项
    judge_backend = backend if backend_ok else None
    metrics.append(blind.judge(responses, blind_cases, judge_backend))
    metrics.append(fidelity.judge(responses, chats, judge_backend))
    metrics.append(fusion.judge_main(responses, fusion_cases, judge_backend))
    metrics.append(fusion.judge_accent(responses, fusion_cases, judge_backend))

    meta = {
        "回复目录": str(responses_dir),
        "回复条数": len(responses),
        "评审后端": f"{args.backend}（{backend_reason}）",
        "随机模拟次数": args.runs,
        "颜文字判定": args.kaomoji,
    }

    if args.out:
        reporter.save(metrics, args.out, meta)
        print(f"报告已写入 {args.out}")

    if args.json:
        print(json.dumps({"meta": meta, "metrics": metrics}, ensure_ascii=False, indent=2))
    else:
        print(reporter.render(metrics, meta))

    failed = [item for item in metrics if not item.get("skipped") and not item.get("passed")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
