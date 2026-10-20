"""场景自适应指标。

PRD 通过线：全部正确降档或关闭。
判定分两类：
- 结构类：代码块 / 表格内零助词（看 check_density 的违规项）。
- 强度类：密度不超过该场景允许的上限（降档后的实际密度）。
"""

from __future__ import annotations

import re

from .common import (
    analyze,
    check_density,
    is_style_off,
    metric,
    missing_replies,
    skipped_metric,
)

# 违规类型 → 用例 expect 里的期望键；类型名与生产脚本同源。
STRUCTURE_TYPES = {
    check_density.VIOLATION_TYPES["code"]: "no_particles_in_code",
    check_density.VIOLATION_TYPES["table"]: "no_particles_in_table",
    check_density.VIOLATION_TYPES["link"]: "no_particles_in_link",
}


def judge(responses: dict, cases: dict) -> dict:
    checked = 0
    failures = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        checked += 1
        expect = case.get("expect", {})
        level = expect.get("density_level") or "standard"
        result = analyze(reply, case.get("style"), density_level=level)
        problems = []

        for violation in result["violations"]:
            key = STRUCTURE_TYPES.get(violation["type"])
            if key and expect.get(key):
                problems.append(f"{violation['type']}：{violation['detail']}")

        cap = expect.get("max_particles_per_100")
        if cap is not None and result["modal_per_100"] > cap:
            problems.append(
                f"密度未降档：{result['modal_per_100']} 次/百字，上限 {cap}"
            )

        for pattern in expect.get("must_match", []):
            if not re.search(pattern, reply):
                problems.append(f"缺少必需内容（规则 {pattern}）")
        for pattern in expect.get("must_not_match", []):
            hit = re.search(pattern, reply)
            if hit:
                problems.append(f"出现了禁止内容「{hit.group(0)}」（规则 {pattern}）")

        if expect.get("style_off") and not is_style_off(reply, result, case.get("style")):
            problems.append("期望关闭风格，但回复里仍有助词 / 颜文字 / 口头禅")

        if problems:
            failures.append({
                "case_id": case["id"],
                "scene": case.get("scene"),
                "style": case.get("style"),
                "reason": "；".join(problems),
            })

    if checked == 0:
        return skipped_metric("场景自适应", "全部正确降档或关闭", "没有可评测的回复。")

    bad = len(failures)
    detail = (f"共检查 {checked} 条场景用例，覆盖代码、表格、高风险、排查步骤、"
              "情绪低落、危机、正式要求与非中文。")
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        "场景自适应",
        "全部正确降档或关闭",
        f"{checked - bad}/{checked} 条通过",
        bad == 0,
        detail=detail,
        failures=failures,
    )
