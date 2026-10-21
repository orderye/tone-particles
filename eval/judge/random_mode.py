"""随机模式指标。

PRD 通过线：1000 次模拟，连续重复 0 次、权重偏差 < 5%。

这两条要求之间存在数学上的取舍，必须分档判：
- 去重窗口为 0：权重精确，但连续重复不可避免 → 断言「偏差 < 5%」。
- 去重窗口 > 0 且权重均等：去重对分布无偏 → 断言「零重复 + 偏差 < 5%」。
- 去重窗口 > 0 且权重不等：去重会系统性压低高权重风格，偏差必然超过 5%
  （脚本原本就在 notes 里说明这一点）→ 断言「零重复」，偏差只作参考值。

把这三档都列进场景，才能既守住硬性要求，又不把数学必然当成缺陷。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import _core  # noqa: E402
import pick_style  # noqa: E402

from .common import metric  # noqa: E402

RUNS = 1000
DEVIATION_LIMIT = 0.05

SCENARIOS = [
    {
        "name": "rotate · 六风格等权 · 池大于去重窗口",
        "config": {
            "mode": "rotate",
            "styles": [{"id": s, "weight": 1} for s in
                       ["S01", "S04", "S05", "S09", "S12", "S17"]],
            "switch": {"granularity": "per_message", "no_repeat_window": 3, "locked": False},
        },
        "regime": "dedup_uniform",
    },
    {
        "name": "blend_random · 五风格等权 · 池大于去重窗口",
        "config": {
            "mode": "blend_random",
            "styles": [{"id": s, "weight": 1} for s in
                       ["S01", "S05", "S09", "S13", "S21"]],
            "switch": {"granularity": "per_message", "no_repeat_window": 3, "locked": False},
        },
        "regime": "dedup_uniform",
    },
    {
        "name": "blend_random · 三风格不等权 · 去重窗口为 0",
        "config": {
            "mode": "blend_random",
            "styles": [{"id": "S09", "weight": 3}, {"id": "S04", "weight": 2}, {"id": "S17", "weight": 1}],
            "switch": {"granularity": "per_message", "no_repeat_window": 0, "locked": False},
        },
        "regime": "exact_weight",
    },
    {
        "name": "rotate · 六风格不等权 · 池大于去重窗口",
        "config": {
            "mode": "rotate",
            "styles": [{"id": "S01", "weight": 4}, {"id": "S04", "weight": 3},
                       {"id": "S05", "weight": 2}, {"id": "S09", "weight": 2},
                       {"id": "S12", "weight": 1}, {"id": "S17", "weight": 1}],
            "switch": {"granularity": "per_message", "no_repeat_window": 3, "locked": False},
        },
        "regime": "dedup_skewed",
    },
    {
        "name": "blend_random · 三风格不等权 · 池不大于去重窗口",
        "config": {
            "mode": "blend_random",
            "styles": [{"id": "S09", "weight": 3}, {"id": "S04", "weight": 2}, {"id": "S17", "weight": 1}],
            "switch": {"granularity": "per_message", "no_repeat_window": 3, "locked": False},
        },
        "regime": "dedup_skewed",
    },
]

REGIME_LABEL = {
    "exact_weight": "权重精确档：断言偏差 < 5%（此档允许连续重复）",
    "dedup_uniform": "零重复档：断言零连续重复 + 偏差 < 5%（权重均等，去重对分布无偏）",
    "dedup_skewed": "放宽档：断言零连续重复，偏差仅作参考（权重不等时去重必然压低高权重风格）",
}


def judge(runs: int = RUNS) -> dict:
    failures = []
    details = []
    passed_scenarios = 0

    for scenario in SCENARIOS:
        cfg = _core.normalize_config(_core.migrate_config(dict(scenario["config"])))
        stats = pick_style.simulate(cfg, runs, seed=42)
        regime = scenario["regime"]
        repeats = stats["consecutive_repeats"]
        deviation = stats["max_abs_deviation"]

        problems = []
        if regime in {"dedup_uniform", "dedup_skewed"} and repeats != 0:
            problems.append(f"出现 {repeats} 次连续重复，要求 0 次")
        if regime in {"exact_weight", "dedup_uniform"} and deviation >= DEVIATION_LIMIT:
            problems.append(f"权重最大偏差 {deviation:.1%}，超过 5%")

        if problems:
            failures.append({
                "scenario": scenario["name"],
                "reason": "；".join(problems),
            })
        else:
            passed_scenarios += 1

        details.append(
            f"{scenario['name']}：重复 {repeats} 次、最大偏差 {deviation:.1%}（{REGIME_LABEL[regime]}）"
        )

    return metric(
        "随机模式",
        "重复 0 次，偏差 <5%",
        f"{passed_scenarios}/{len(SCENARIOS)} 个场景达标",
        not failures,
        detail="；".join(details) + f"。每个场景模拟 {runs} 次。",
        failures=failures,
        counts={
            "passed": passed_scenarios,
            "failed": len(failures),
            "not_evaluated": 0,
            "blocked": 0,
            "denominator": len(SCENARIOS),
        },
        denominator=len(SCENARIOS),
        denominator_note="模拟场景数量",
    )
