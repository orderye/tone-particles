"""融合指标。

PRD 通过线：
- 主风格识别 ≥70%
- 副风格签名元素出现率 ≥50%

两条判据都能有确定性版本：签名元素里带引号的短语是可以直接在回复里搜的。
有评审模型时改用模型判断（更贴近人看到的「像不像那个风格」）。

**没有评审模型时，这两项不报「达标」。** PRD 的这两条是模型类目标（盲测、
内容保真、融合识别），只有真的跑了对应评测才能宣称通过。确定性签名命中只作为
参考值写在 detail 里，指标状态是「未评测」——把参考值渲染成达标，就是把
「没测到」说成「测过了」。
"""

from __future__ import annotations

import re

from .common import (
    _core,
    answered,
    blocked_metric,
    call_judge,
    catalog,
    metric,
    missing_replies,
    skipped_metric,
    style_meta,
)

FUSION_RUBRIC_VERSION = "fusion-v1"

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


def _deterministic_hit(responses, cases) -> tuple:
    """确定性参考：签名元素是否在回复里出现。返回 (命中数, 已检查数, 命中明细)。"""
    hits = 0
    checked = 0
    detail = []
    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        checked += 1
        fragments = signature_fragments(case["style"])
        hit = next((item for item in fragments if item in reply), None)
        if hit:
            hits += 1
            detail.append(f"{case['id']} 命中「{hit}」")
    return hits, checked, detail


def judge_main(responses: dict, cases: dict, backend=None) -> dict:
    use_model = bool(backend is not None and backend.available()[0])

    checked = 0
    correct = 0
    failures = []
    notes = []
    blocked = []
    missing = missing_replies(cases, responses)

    if not use_model:
        hits, checked_total, _ = _deterministic_hit(responses, cases)
        reference = (f"{hits}/{checked_total}"
                     if checked_total else "无可评测的回复")
        detail = (f"未配置评审后端，本项未评测。确定性参考：主风格签名元素命中 "
                  f"{reference}——仅供参考，不作为模型类指标的达标依据。")
        return skipped_metric("融合主风格识别", "≥70%", detail,
                              requires_model=True, rubric_version=FUSION_RUBRIC_VERSION)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        meta = style_meta(case["main"])
        expected = f"{meta['id']} {meta['name']}"
        options = [f"{item['id']} {item['name']}" for item in catalog().values()]
        verdict, blocked_reason = call_judge(backend, MAIN_RUBRIC, {
            "case_id": case["id"],
            "display": reply,
            "options": options,
        })
        if blocked_reason:
            blocked.append({"case_id": case["id"], "reason": blocked_reason})
            continue
        if not answered(verdict, "choice"):
            notes.append({"case_id": case["id"], "reason": "评审未给出结论，未计入"})
            continue
        checked += 1
        if verdict["choice"] == expected:
            correct += 1
        else:
            failures.append({
                "case_id": case["id"],
                "expected": expected,
                "chosen": verdict["choice"],
                "reason": verdict.get("reason", ""),
            })

    for case_id in missing:
        notes.append({"case_id": case_id, "reason": "缺回复，未计入"})

    counts = {
        "passed": correct,
        "failed": len(failures),
        "not_evaluated": len(notes),
        "blocked": len(blocked),
        "denominator": checked,
    }

    if checked == 0:
        if blocked:
            return blocked_metric(
                "融合主风格识别", "≥70%",
                f"评审通道不可用，{len(blocked)} 条用例没能得出结论。",
                blocked=blocked, requires_model=True,
                rubric_version=FUSION_RUBRIC_VERSION)
        return skipped_metric(
            "融合主风格识别", "≥70%",
            f"没有可用的评审结果（{len(notes)} 条未作答）。",
            notes=notes, blocked=blocked, counts=counts,
            requires_model=True, rubric_version=FUSION_RUBRIC_VERSION)

    ratio = correct / checked
    detail = (f"判据：评审模型（从 21 个风格中选主导风格）。"
              f"分母 = 实际评审条数（{checked}）。")
    if notes:
        detail += f" 另有 {len(notes)} 条未计入。"
    if blocked:
        detail += f" 另有 {len(blocked)} 条被阻塞。"
    return metric(
        "融合主风格识别",
        "≥70%",
        f"{ratio * 100:.1f}%（{correct}/{checked}）",
        ratio >= 0.70,
        detail=detail,
        failures=failures,
        notes=notes,
        blocked=blocked,
        counts=counts,
        requires_model=True,
        denominator=checked,
        denominator_note="实际评审条数（缺回复与评审未作答不计入分母）",
        rubric_version=FUSION_RUBRIC_VERSION,
    )


def judge_accent(responses: dict, cases: dict, backend=None) -> dict:
    use_model = bool(backend is not None and backend.available()[0])

    checked = 0
    present = 0
    failures = []
    notes = []
    blocked = []
    missing = missing_replies(cases, responses)

    if not use_model:
        hits, checked_total, _ = _deterministic_hit(responses, cases)
        reference = (f"{hits}/{checked_total}"
                     if checked_total else "无可评测的回复")
        detail = (f"未配置评审后端，本项未评测。确定性参考：副风格签名元素命中 "
                  f"{reference}——仅供参考，不作为模型类指标的达标依据。")
        return skipped_metric("副风格签名元素出现率", "≥50%", detail,
                              requires_model=True, rubric_version=FUSION_RUBRIC_VERSION)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        meta = style_meta(case["accent"])
        verdict, blocked_reason = call_judge(backend, ACCENT_RUBRIC, {
            "case_id": case["id"],
            "display": reply,
            "signature": meta.get("signature", []),
        })
        if blocked_reason:
            blocked.append({"case_id": case["id"], "reason": blocked_reason})
            continue
        if not answered(verdict, "present"):
            notes.append({"case_id": case["id"], "reason": "评审未给出结论，未计入"})
            continue
        checked += 1
        if verdict["present"] is True:
            present += 1
        else:
            failures.append({
                "case_id": case["id"],
                "accent": f"{meta['id']} {meta['name']}",
                "reason": verdict.get("reason", "未出现签名元素"),
            })

    for case_id in missing:
        notes.append({"case_id": case_id, "reason": "缺回复，未计入"})

    counts = {
        "passed": present,
        "failed": len(failures),
        "not_evaluated": len(notes),
        "blocked": len(blocked),
        "denominator": checked,
    }

    if checked == 0:
        if blocked:
            return blocked_metric(
                "副风格签名元素出现率", "≥50%",
                f"评审通道不可用，{len(blocked)} 条用例没能得出结论。",
                blocked=blocked, requires_model=True,
                rubric_version=FUSION_RUBRIC_VERSION)
        return skipped_metric(
            "副风格签名元素出现率", "≥50%",
            f"没有可用的评审结果（{len(notes)} 条未作答）。",
            notes=notes, blocked=blocked, counts=counts,
            requires_model=True, rubric_version=FUSION_RUBRIC_VERSION)

    ratio = present / checked
    detail = (f"判据：评审模型（判断是否出现签名元素）。"
              f"分母 = 实际评审条数（{checked}）。")
    if notes:
        detail += f" 另有 {len(notes)} 条未计入。"
    if blocked:
        detail += f" 另有 {len(blocked)} 条被阻塞。"
    return metric(
        "副风格签名元素出现率",
        "≥50%",
        f"{ratio * 100:.1f}%（{present}/{checked}）",
        ratio >= 0.50,
        detail=detail,
        failures=failures,
        notes=notes,
        blocked=blocked,
        counts=counts,
        requires_model=True,
        denominator=checked,
        denominator_note="实际评审条数（缺回复与评审未作答不计入分母）",
        rubric_version=FUSION_RUBRIC_VERSION,
    )
