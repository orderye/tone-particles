"""语义锚点保真指标。

用例可以声明两类字段：

- `anchors`：必须**原样出现**的关键片段（数字、金额、日期、单位、百分比、
  版本号、命令、代码片段、URL、文件路径、实体名、表格单元格）。
- `forbidden_anchors`：绝不能出现的片段（写错的号码、金额、结论）。

本判分器做确定性的字面校验：数字类锚点按「独立数字」匹配，避免「120」被
「1200」误判为命中；其余锚点按子串匹配。

**它能证明什么、不能证明什么：**
- 能证明：关键片段没有被改写、被截断、被替换成别的值。
- 不能证明：整段语义等价。语义等价仍然需要模型或人工评审（见 fidelity.py），
  且它的判定边界见那里写的「运行时边界」说明——真实运行时系统没有同一条问题的
  无风格基线回复，做不了真正的双文本比对。

确定性检查的价值在于它不依赖模型、每次都跑、结果可复现：它守住「数字没被改
」这条底线，剩下的语义问题交给评审层。
"""

from __future__ import annotations

import re

from .common import metric, missing_replies, skipped_metric

# 锚点匹配的容错：数字前后不能再接数字，避免子串误命中。
_CACHE: dict = {}


def _pattern(anchor: str):
    cached = _CACHE.get(anchor)
    if cached is not None:
        return cached
    pattern = re.escape(anchor)
    if anchor[:1].isdigit():
        pattern = r"(?<![0-9])" + pattern
    if anchor[-1:].isdigit():
        pattern = pattern + r"(?![0-9])"
    compiled = re.compile(pattern)
    _CACHE[anchor] = compiled
    return compiled


def present(reply: str, anchor: str) -> bool:
    """锚点是否原样出现。"""
    return bool(_pattern(anchor).search(reply))


def judge(responses: dict, cases: dict) -> dict:
    checked = 0
    total = 0
    kept = 0
    failures = []
    notes = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        anchors = list(case.get("anchors") or [])
        forbidden = list(case.get("forbidden_anchors") or [])
        if not anchors and not forbidden:
            continue
        reply = responses.get(case["id"])
        if reply is None:
            notes.append({"case_id": case["id"], "reason": "缺回复，未计入"})
            continue
        checked += 1
        problems = []
        for anchor in anchors:
            total += 1
            if present(reply, anchor):
                kept += 1
            else:
                problems.append(f"关键片段「{anchor}」未原样出现")
        for anchor in forbidden:
            total += 1
            if present(reply, anchor):
                problems.append(f"出现了不该出现的片段「{anchor}」")
            else:
                kept += 1
        if problems:
            failures.append({
                "case_id": case["id"],
                "style": case.get("style"),
                "reason": "；".join(problems),
            })

    if total == 0:
        return skipped_metric(
            "语义锚点保真", "100% 锚点原样保留",
            f"没有声明锚点的用例，或没有可评测的回复（{len(notes)} 条缺回复）。")

    bad = len(failures)
    detail = (f"共校验 {total} 个锚点（{checked} 条回复）。"
              "这是字面校验：能守住「关键片段没被改」，不等于整段语义等价——"
              "语义等价看「内容保真」那一项。")
    if notes:
        detail += f" 另有 {len(notes)} 条缺回复未计入。"
    counts = {
        "passed": kept,
        "failed": total - kept,
        "not_evaluated": len(notes),
        "blocked": 0,
        "denominator": total,
    }
    return metric(
        "语义锚点保真",
        "100% 锚点原样保留",
        f"{kept}/{total} 个锚点保留（{checked} 条回复）",
        bad == 0,
        detail=detail,
        failures=failures,
        notes=notes,
        counts=counts,
        denominator=total,
        denominator_note="声明过的锚点总数（缺回复的用例不计入）",
    )
