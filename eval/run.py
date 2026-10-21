#!/usr/bin/env python3
"""评测入口。

用法：
    python3 eval/run.py                          # 只跑确定性指标
    python3 eval/run.py --backend chat_completions   # 加上模型评审的三项
    python3 eval/run.py --generate --backend chat_completions   # 先生成回复再评测
    python3 eval/run.py --out eval/report.md     # 写出报告（.md 与 .json）
    python3 eval/run.py --strict                 # 严格验收：模型类指标必须真的评测过

确定性指标（助词密度、硬规则、语义锚点、颜文字、场景自适应、安全红队、随机）
不调用任何模型，读的是 eval/fixtures/responses/ 里的回复文件。需要模型的三项
（风格盲测、内容保真、融合识别）在没有可用后端时标记为「未评测」——**不是通过**。

退出码：
    0  没有指标不达标（被阻塞的指标也算不达标）
    1  有指标不达标，或被阻塞
    2  严格模式下有模型类指标「未评测」——发布候选验收不接受这种状态
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from backends import get_backend  # noqa: E402
from judge import anchors, blind, density, fidelity, fusion, kaomoji, random_mode, redteam, rules, scene  # noqa: E402
from judge.common import load_cases, load_responses  # noqa: E402
import generate as generator  # noqa: E402
import report as reporter  # noqa: E402
import validate_cases  # noqa: E402

RESPONSES_DIR = EVAL_ROOT / "fixtures" / "responses"
CASES_DIR = EVAL_ROOT / "cases"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_STRICT = 2


def _git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = proc.stdout.strip()
    return commit or "unknown"


def _repo_version() -> str:
    version_file = REPO_ROOT / "VERSION"
    if not version_file.exists():
        return "unknown"
    return version_file.read_text(encoding="utf-8").strip() or "unknown"


def _cases_digest() -> str:
    """评测数据的哈希：数据集变了，报告就该能看出来。"""
    digest = hashlib.sha256()
    for path in sorted(CASES_DIR.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def collect_meta(args, backend, backend_ok, backend_reason, responses) -> dict:
    """报告的运行信息。取不到的元数据写 unknown，不许伪造。"""
    return {
        "仓库版本": _repo_version(),
        "Git commit": _git_commit(),
        "Python": platform.python_version(),
        "平台": f"{platform.system()} {platform.release()}",
        "评测数据哈希": _cases_digest(),
        "回复目录": str(responses and args.responses or RESPONSES_DIR),
        "回复条数": len(responses),
        "评审后端": f"{args.backend}（{backend_reason}）",
        "后端元信息": backend.metadata() if backend_ok else {"后端": args.backend,
                                                       "模型": "unknown"},
        "随机模拟次数": args.runs,
        "颜文字判定": args.kaomoji,
        "随机种子": args.seed if args.seed is not None else "未设置（每次抽样随机）",
        "严格模式": bool(args.strict or args.strict_all),
    }


def evaluate(args, responses, backend=None, backend_ok=False) -> list:
    """跑完全部指标，返回指标列表。"""
    chats = load_cases("chats")
    blind_cases = load_cases("blind")
    redteam_cases = load_cases("redteam")
    scene_cases = load_cases("scenes")
    fusion_cases = load_cases("fusion")

    metrics = []

    # 确定性指标
    metrics.append(density.judge(responses, chats))
    metrics.append(rules.judge(responses, chats))
    metrics.append(anchors.judge(responses, chats))
    if args.kaomoji in ("off", "both"):
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
    return metrics


def classify(metrics, strict: bool, strict_all: bool) -> dict:
    """把指标按状态归类，返回判定结果。"""
    failed = [item for item in metrics if item.get("status") == "failed"]
    blocked = [item for item in metrics if item.get("status") == "blocked"]
    not_evaluated = [item for item in metrics if item.get("status") == "not_evaluated"]
    model_pending = [item for item in not_evaluated if item.get("requires_model")]
    other_pending = [item for item in not_evaluated if not item.get("requires_model")]

    exit_code = EXIT_OK
    if failed or blocked:
        exit_code = EXIT_FAILED
    if strict and model_pending:
        exit_code = EXIT_STRICT
    if strict_all and not_evaluated:
        exit_code = EXIT_STRICT
    return {
        "failed": failed,
        "blocked": blocked,
        "not_evaluated": not_evaluated,
        "model_pending": model_pending,
        "other_pending": other_pending,
        "strict": bool(strict or strict_all),
        "exit_code": exit_code,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="语气助词 Skill 评测")
    parser.add_argument("--responses", help="回复目录，默认 eval/fixtures/responses")
    parser.add_argument("--backend", default="none",
                        help="评审后端：none / fixture / chat_completions / messages_api / manual")
    parser.add_argument("--kaomoji", choices=["off", "on", "both"], default="both",
                        help="颜文字判定：off 只判关闭态 / on 只判开启态 / both 两态都判")
    parser.add_argument("--generate", action="store_true", help="先生成缺失的回复")
    parser.add_argument("--overwrite", action="store_true", help="生成时覆盖已有回复")
    parser.add_argument("--density", default="standard", choices=["light", "standard", "strong"],
                        help="生成回复时使用的密度档位")
    parser.add_argument("--runs", type=int, default=1000, help="随机模式的模拟次数")
    parser.add_argument("--seed", type=int, default=None,
                        help="随机模拟的种子；不设则每次结果不同")
    parser.add_argument("--out", help="报告输出路径（同时写出 .json）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--strict", action="store_true",
                        help="严格验收：模型类指标必须真的评测过，否则返回退出码 2")
    parser.add_argument("--strict-all", action="store_true",
                        help="更严格：任何「未评测」都返回退出码 2")
    parser.add_argument("--skip-validate", action="store_true",
                        help="跳过用例结构校验（不建议）")
    args = parser.parse_args(argv)

    if not args.skip_validate:
        problems = validate_cases.validate_all()
        if problems:
            print("评测用例结构校验未通过，已中止：", file=sys.stderr)
            for item in problems:
                print(f"  - {item}", file=sys.stderr)
            return EXIT_FAILED

    responses_dir = Path(args.responses) if args.responses else RESPONSES_DIR
    case_sets = [load_cases(name) for name in
                 ("chats", "blind", "redteam", "scenes", "fusion")]

    backend = get_backend(args.backend)
    backend_ok, backend_reason = backend.available()

    if args.generate:
        if not backend_ok:
            raise SystemExit(f"生成需要可用的后端，当前不可用：{backend_reason}")
        if not getattr(backend, "can_generate", False):
            raise SystemExit(
                f"{args.backend} 后端不支持生成回复；生成请用 chat_completions / "
                "messages_api，或把回复手工放进 fixtures/responses/。")
        print("生成回复中……")
        stats = generator.generate_all(
            backend, case_sets, responses_dir,
            density_level=args.density,
            only_missing=not args.overwrite,
        )
        print(f"  新生成 {stats['generated']} 条，跳过已有 {stats['skipped']} 条，"
              f"失败 {stats['failed']} 条。")

    responses = load_responses(responses_dir)
    metrics = evaluate(args, responses, backend, backend_ok)
    meta = collect_meta(args, backend, backend_ok, backend_reason, responses)
    verdict = classify(metrics, args.strict, args.strict_all)

    if args.out:
        reporter.save(metrics, args.out, meta, verdict)
        print(f"报告已写入 {args.out}")

    if args.json:
        print(json.dumps({"meta": meta, "metrics": metrics, "verdict": verdict},
                         ensure_ascii=False, indent=2))
    else:
        print(reporter.render(metrics, meta, verdict))

    return verdict["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
