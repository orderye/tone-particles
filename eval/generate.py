"""生成阶段：把评测用例变成模型回复并存档。

判分与生成彻底分开——生成需要模型，判分不需要。生成结果存进
eval/fixtures/responses/ 后，判分就能离线复现；CI 也因此不需要模型额度。
"""

from __future__ import annotations

import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import compose_prompt  # noqa: E402

LENGTH_HINT = "\n\n回复长度控制在 {low}–{high} 字之间；内容要完整，不要为了短而省略信息。"


def case_prompt(case: dict, pool: list) -> str:
    if case.get("user_input"):
        return case["user_input"]
    if "prompt" in case and pool:
        return pool[case["prompt"]]
    return ""


def case_members(case: dict):
    if case.get("main"):
        accent = case.get("accent")
        if accent:
            return [(case["main"], 4), (accent, 2)]
        return [(case["main"], 1)]
    style = case.get("style")
    return [(style, 1)] if style else []


def build_system(case: dict, density_level: str = "standard") -> str:
    members = case_members(case)
    if not members:
        return ""
    variants = case.get("variants")
    payload = compose_prompt.compose(members, None, density_level, variants)
    minimum = case.get("min_chars", 150)
    maximum = max(minimum * 2, 300)
    return payload["prompt"] + LENGTH_HINT.format(low=minimum, high=maximum)


def generate_all(backend, case_sets, responses_dir, *, density_level="standard",
                 only_missing=True, log=print) -> dict:
    """对所有用例生成回复，返回统计。"""
    responses_dir = Path(responses_dir)
    responses_dir.mkdir(parents=True, exist_ok=True)
    stats = {"generated": 0, "skipped": 0, "failed": 0}
    for cases in case_sets:
        pool = cases.get("pool", [])
        for case in cases["cases"]:
            path = responses_dir / f"{case['id']}.md"
            if only_missing and path.exists():
                stats["skipped"] += 1
                continue
            system = build_system(case, density_level)
            user = case_prompt(case, pool)
            if not system or not user:
                stats["failed"] += 1
                continue
            try:
                reply = backend.generate(system, user)
            except (Exception, SystemExit) as exc:
                # SystemExit 也是 BaseException 的子类，普通的 except Exception
                # 接不住它——后端抛出的接口错误会直接把整批评测打断。
                log(f"  ! {case['id']} 生成失败：{exc}")
                stats["failed"] += 1
                continue
            if not reply or not reply.strip():
                log(f"  ! {case['id']} 返回为空")
                stats["failed"] += 1
                continue
            path.write_text(reply, encoding="utf-8")
            stats["generated"] += 1
    return stats
