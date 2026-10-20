"""助词密度指标。

PRD 通过线：≥90% 的回复落入该风格的密度区间。

两处口径需要说明：
1. 短于用例要求长度的回复不计入分母。README 已指出 PRD 附录的标称区间取自
   20–60 字的短句，按工具口径密度普遍偏高，标定必须用 150–400 字的完整回复。
2. 判定带 ±0.5 次/百字的容差。标称区间本身是短句口径的产物，直接套到长回复上
   会把取整误差判成风格问题；容差只影响「是否落在区间内」这一步，实测值照实
   报出，报告里也会标注用了容差。
"""

from __future__ import annotations

from .common import analyze, metric, missing_replies, skipped_metric

DEFAULT_TOLERANCE = 0.5


def judge(responses: dict, cases: dict, *, density_level: str = "standard",
          tolerance: float = DEFAULT_TOLERANCE) -> dict:
    samples = 0
    in_range = 0
    failures = []
    too_short = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        style = case.get("style")
        if not style:
            continue
        level = case.get("density_level") or density_level
        result = analyze(reply, style, density_level=level)
        minimum = case.get("min_chars", 150)
        if result["chars"] < minimum:
            too_short.append({
                "case_id": case["id"],
                "chars": result["chars"],
                "required": minimum,
            })
            continue
        samples += 1
        low, high = result["target"]
        value = result["modal_per_100"]
        if value < low - tolerance:
            status = "below"
        elif value > high + tolerance:
            status = "above"
        else:
            status = "in_range"
        if status == "in_range":
            in_range += 1
        else:
            failures.append({
                "case_id": case["id"],
                "style": style,
                "modal_per_100": value,
                "target": result["target"],
                "status": status,
                "reason": f"密度{status}：{value} 次/百字，目标区间 {result['target']}"
                          f"（容差 ±{tolerance}）",
            })

    if samples == 0:
        return skipped_metric(
            "助词密度",
            "≥90% 落入风格区间",
            f"没有长度达标的回复可评测（{len(too_short)} 条长度不足）。",
        )

    ratio = in_range / samples
    detail = f"{in_range}/{samples} 条落入区间（{ratio * 100:.1f}%），按 ±{tolerance} 次/百字容差判定。"
    if too_short:
        detail += f" 另有 {len(too_short)} 条长度不足未计入。"
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        "助词密度",
        "≥90% 落入风格区间",
        f"{ratio * 100:.1f}%（{in_range}/{samples}）",
        ratio >= 0.90,
        detail=detail,
        failures=failures + too_short,
    )
