"""融合指标。

PRD 通过线：
- 主风格识别 ≥70%
- 副风格签名元素出现率 ≥50%

两条判据都能有确定性版本：签名元素里带引号的短语是可以直接在回复里搜的。
有评审模型时改用模型判断（更贴近人看到的「像不像那个风格」），没有时退回
确定性版本，并在报告里注明用的是哪种判据。
"""

from __future__ import annotations

import re

from .common import _core, catalog, metric, missing_replies, skipped_metric

# 只有标点或通用词的签名片段不作判据——几乎每条回复都会命中。
GENERIC_FRAGMENTS = {"……", "呵", "嗯", "哦", "吧", "呢"}

MAIN_RUBRIC = """
给定的回复是两种风格融合后的产物。请判断「哪一种风格占了主导」，
从 21 个候选里选一个，只依据表达层判断，不要评价内容质量。

只输出 JSON：{"choice": "<候选风格里原样的一项>", "reason": "<不超过 30 字>"}
"""

ACCENT_RUBRIC = """
下面列出的是某个副风格的签名元素。请判断给定回复里是否**出现了至少一个**签名元素。

只输出 JSON：{"present": true 或 false, "found": "<出现的那个签名元素>", "reason": "<不超过 30 字>"}
"""


def signature_fragments(style_id: str) -> list:
    """风格签名元素里可以直接在回复中搜到的引号短语。"""
    meta = catalog()[style_id]
    text = _core.style_text(meta)
    section = _core.extract_field(text, "签名元素")
    fragments = []
    for quoted in re.findall(r"「([^」]+)」", section):
        quoted = quoted.strip()
        if len(quoted) < 2 or quoted in GENERIC_FRAGMENTS:
            continue
        fragments.append(quoted)
    return fragments


def judge_main(responses: dict, cases: dict, backend=None) -> dict:
    checked = 0
    correct = 0
    failures = []
    missing = missing_replies(cases, responses)
    method = "确定性（主风格签名元素命中）"

    if backend is not None:
        ok, _ = backend.available()
        if ok:
            method = "评审模型（从 21 个风格中选主导风格）"

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        meta = catalog()[case["main"]]
        expected = f"{meta['id']} {meta['name']}"
        checked += 1

        if method.startswith("评审模型"):
            options = [f"{item['id']} {item['name']}" for item in catalog().values()]
            verdict = backend.judge(MAIN_RUBRIC, {
                "case_id": case["id"],
                "display": reply,
                "options": options,
            })
            choice = (verdict or {}).get("choice")
            if choice == expected:
                correct += 1
            else:
                failures.append({
                    "case_id": case["id"],
                    "expected": expected,
                    "chosen": choice,
                    "reason": (verdict or {}).get("reason", ""),
                })
        else:
            fragments = signature_fragments(case["main"])
            hit = next((item for item in fragments if item in reply), None)
            if hit:
                correct += 1
            else:
                failures.append({
                    "case_id": case["id"],
                    "expected": expected,
                    "reason": f"未命中主风格签名元素，候选片段：{'、'.join(fragments) or '无'}",
                })

    if checked == 0:
        return skipped_metric("融合主风格识别", "≥70%", "没有可评测的回复。")

    ratio = correct / checked
    detail = f"判据：{method}。"
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        "融合主风格识别",
        "≥70%",
        f"{ratio * 100:.1f}%（{correct}/{checked}）",
        ratio >= 0.70,
        detail=detail,
        failures=failures,
    )


def judge_accent(responses: dict, cases: dict, backend=None) -> dict:
    checked = 0
    present = 0
    failures = []
    missing = missing_replies(cases, responses)
    method = "确定性（副风格签名元素命中）"

    if backend is not None:
        ok, _ = backend.available()
        if ok:
            method = "评审模型（判断是否出现签名元素）"

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        meta = catalog()[case["accent"]]
        checked += 1

        if method.startswith("评审模型"):
            verdict = backend.judge(ACCENT_RUBRIC, {
                "case_id": case["id"],
                "display": reply,
                "signature": meta.get("signature", []),
            })
            if (verdict or {}).get("present") is True:
                present += 1
            else:
                failures.append({
                    "case_id": case["id"],
                    "accent": f"{meta['id']} {meta['name']}",
                    "reason": (verdict or {}).get("reason", "未出现签名元素"),
                })
        else:
            fragments = signature_fragments(case["accent"])
            hit = next((item for item in fragments if item in reply), None)
            if hit:
                present += 1
            else:
                failures.append({
                    "case_id": case["id"],
                    "accent": f"{meta['id']} {meta['name']}",
                    "reason": f"未命中副风格签名元素，候选片段：{'、'.join(fragments) or '无'}",
                })

    if checked == 0:
        return skipped_metric("副风格签名元素出现率", "≥50%", "没有可评测的回复。")

    ratio = present / checked
    detail = f"判据：{method}。"
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        "副风格签名元素出现率",
        "≥50%",
        f"{ratio * 100:.1f}%（{present}/{checked}）",
        ratio >= 0.50,
        detail=detail,
        failures=failures,
    )
