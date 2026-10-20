"""颜文字指标。

PRD 通过线：关闭时抽检 0 个；开启时全部取自该风格库、频率符合倾向与档位、
严肃场景为 0，整体 100% 符合。

本判分器按「用户配置里的开关状态」分别跑两遍：
- 关闭态：任何颜文字都算违规。
- 开启态：必须取自该风格的颜文字库、单条不超过 1 个、不与 emoji 同条、
  代码 / 表格等严肃场景内不得出现。

频率按风格倾向跨回复统计（PRD 4.6 第 6 条），单条回复只能判上限。
"""

from __future__ import annotations

from .common import (
    _core,
    analyze,
    check_density,
    metric,
    missing_replies,
    skipped_metric,
    style_meta,
)

# 违规类型与生产脚本同源（scripts/check_density.py）
KAOMOJI_TYPES = check_density.KAOMOJI_TYPES


def judge(responses: dict, cases: dict, *, kaomoji_enabled: bool = False) -> dict:
    checked = 0
    failures = []
    total_kaomoji = 0
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        style = case.get("style")
        result = analyze(reply, style, kaomoji_enabled=kaomoji_enabled)
        checked += 1
        total_kaomoji += result["kaomoji_count"]
        for violation in result["violations"]:
            if violation["type"] not in KAOMOJI_TYPES:
                continue
            failures.append({
                "case_id": case["id"],
                "type": violation["type"],
                "detail": violation["detail"],
                "excerpt": violation.get("excerpt", ""),
            })

    if checked == 0:
        return skipped_metric("颜文字", "100% 符合", "没有可评测的回复。")

    bad = len(failures)
    state = "开启" if kaomoji_enabled else "关闭"
    detail = (f"按配置开关为「{state}」判定。"
              + ("关闭态下出现颜文字即违规。" if not kaomoji_enabled else
                 "开启态下颜文字须取自该风格库、单条 ≤1、不与 emoji 同条、不出现在代码与表格中。"))
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        f"颜文字（{state}态）",
        "100% 符合",
        f"{checked - bad}/{checked} 条通过，全文共 {total_kaomoji} 个颜文字",
        bad == 0,
        detail=detail,
        failures=failures,
    )


def frequency(cases: dict, responses: dict, kaomoji_enabled: bool = True) -> dict:
    """跨回复统计颜文字频率是否落在风格倾向的预算内。

    单条回复判不了频率（PRD 说「约每 N 条 1 个」），所以按同一风格的回复聚合计算。
    """
    per_style = {}
    for case in cases["cases"]:
        reply = responses.get(case["id"])
        style = case.get("style")
        if reply is None or not style:
            continue
        meta = style_meta(style)
        bucket = per_style.setdefault(style, {"replies": 0, "kaomoji": 0, "tendency": meta.get("kaomoji")})
        bucket["replies"] += 1
        bucket["kaomoji"] += analyze(reply, style, kaomoji_enabled=kaomoji_enabled)["kaomoji_count"]

    failures = []
    for style, bucket in sorted(per_style.items()):
        tendency = bucket["tendency"] or "medium"
        budget = _core.kaomoji_budget(tendency)
        allowed = budget * bucket["replies"]
        if bucket["kaomoji"] > allowed + 0.001:
            failures.append({
                "style": style,
                "tendency": tendency,
                "replies": bucket["replies"],
                "kaomoji": bucket["kaomoji"],
                "allowed": round(allowed, 2),
                "reason": f"{style} 倾向「{tendency}」，{bucket['replies']} 条回复最多允许 "
                          f"{allowed:.2f} 个颜文字，实际 {bucket['kaomoji']} 个",
            })

    if not per_style:
        return skipped_metric("颜文字频率", "符合倾向与档位", "没有可评测的回复。")

    return metric(
        "颜文字频率",
        "符合倾向与档位",
        f"{len(per_style) - len(failures)}/{len(per_style)} 个风格达标",
        not failures,
        detail="按风格聚合回复统计：每条回复的颜文字数之和不应超过倾向预算 × 回复数。",
        failures=failures,
    )
