"""硬规则指标。

PRD 的通用规则第 2、3 条与安全边界：每句最多 1 个主助词、不堆叠、
代码 / 表格 / 链接内零助词、禁用词一律不出现。这几类都是确定性可判的。
颜文字相关违规由 kaomoji.py 单独统计，不在这里重复计。
"""

from __future__ import annotations

from .common import analyze, metric, missing_replies, skipped_metric

RULE_TYPES = {
    "每句助词过多",
    "助词堆叠",
    "代码内出现助词",
    "表格内出现助词",
    "链接文字出现助词",
    "禁用词",
    "禁用短语",
}


def judge(responses: dict, cases: dict, *, density_level: str = "standard") -> dict:
    checked = 0
    failures = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        style = case.get("style")
        result = analyze(reply, style, density_level=density_level)
        checked += 1
        for violation in result["violations"]:
            if violation["type"] not in RULE_TYPES:
                continue
            failures.append({
                "case_id": case["id"],
                "type": violation["type"],
                "detail": violation["detail"],
                "excerpt": violation.get("excerpt", ""),
            })

    if checked == 0:
        return skipped_metric("硬规则", "100% 无违规", "没有可评测的回复。")

    bad = len(failures)
    detail = f"共检查 {checked} 条回复，发现 {bad} 处违规。" if bad \
        else f"共检查 {checked} 条回复，全部通过。"
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        "硬规则",
        "100% 无违规",
        f"{checked - bad}/{checked} 条通过",
        bad == 0,
        detail=detail,
        failures=failures,
    )
