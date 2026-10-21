"""风格盲测指标。

PRD 通过线：≥80%。每个风格 ≥3 条回复，评审从 21 个选项中盲选。

评审只拿到「用户输入 + 回复」和 21 个候选风格（顺序按固定种子打乱，保证可复现），
不告诉它这条本来该是哪种风格。没有模型后端时可用人工盲测表录入，
或直接标记为 skipped。

评审过程出错（网络失败、HTTP 错误、返回格式不对）记为「被阻塞」——那是评审
通道的问题，不是「这条回复不像目标风格」。
"""

from __future__ import annotations

import hashlib
import random

from .common import (
    answered,
    call_judge,
    catalog,
    metric,
    missing_replies,
    skipped_metric,
    blocked_metric,
    style_meta,
)

# rubric 版本随判分标准变化。报告里会带上它，避免「改了标准但报告看不出」。
BLIND_RUBRIC_VERSION = "blind-v1"

BLIND_RUBRIC = """
从给定的 21 个候选风格里，选出与这条回复最接近的一种。

判断依据只看表达层：措辞习惯、句式节奏、口头禅与语助词位置、称呼与自称、
情绪强度与距离感。不要评价内容质量，不要因为内容主题相似就选错风格。
如果两种风格都像，选更像的那一种。

只输出 JSON：{"choice": "<候选风格里原样的一项>", "reason": "<不超过 30 字>"}
"""


def _options(seed: int) -> list:
    """21 个候选风格，按固定种子打乱，评审时看不到风格顺序规律。"""
    items = [f"{meta['id']} {meta['name']}" for meta in catalog().values()]
    random.Random(seed).shuffle(items)
    return items


def _stable_seed(case_id: str) -> int:
    """稳定的种子。

    不能用内置 hash()——字符串 hash 每个进程都带随机种子（PYTHONHASHSEED），
    同一条用例在不同次运行里会得到不同的候选顺序，盲测结果无法复现。
    """
    digest = hashlib.md5(case_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def judge(responses: dict, cases: dict, backend=None) -> dict:
    if backend is None:
        return skipped_metric("风格盲测", "≥80% 识别率", "未配置评审后端。",
                              requires_model=True, rubric_version=BLIND_RUBRIC_VERSION)
    ok, reason = backend.available()
    if not ok:
        return skipped_metric("风格盲测", "≥80% 识别率", f"评审后端不可用：{reason}",
                              requires_model=True, rubric_version=BLIND_RUBRIC_VERSION)

    pool = cases.get("pool", [])
    checked = 0
    correct = 0
    failures = []
    notes = []
    blocked = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        prompt = pool[case["prompt"]] if pool else case.get("user_input", "")
        options = _options(_stable_seed(case["id"]))
        meta = style_meta(case["style"])
        expected = f"{meta['id']} {meta['name']}"

        # 盲测泄漏检查：回复里出现目标风格名，评审就能「作弊」，这条不算数。
        if meta["name"] in reply:
            failures.append({
                "case_id": case["id"],
                "expected": expected,
                "chosen": "（未评审）",
                "reason": f"盲测泄漏：回复里出现了目标风格名「{meta['name']}」，本条不作盲测依据。",
            })
            continue

        verdict, blocked_reason = call_judge(backend, BLIND_RUBRIC, {
            "case_id": case["id"],
            "display": f"【用户输入】\n{prompt}\n\n【回复】\n{reply}",
            "options": options,
        })
        if blocked_reason:
            blocked.append({"case_id": case["id"], "reason": blocked_reason})
            continue
        if not answered(verdict, "choice"):
            # 后端没给出结论（如档案里没有这条的评审记录）＝没测到，不算失败
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
        "passed": checked - len([item for item in failures if item.get("chosen") != "（未评审）"]),
        "failed": len(failures),
        "not_evaluated": len(notes),
        "blocked": len(blocked),
        "denominator": checked,
    }

    if checked == 0:
        if failures:
            # 有真失败（例如盲测泄漏）时结论是「不达标」，不是「没测到」。
            return metric(
                "风格盲测", "≥80% 识别率", "0/0",
                False,
                detail="没有可评审的回复，但发现了真失败（见未通过明细）。",
                failures=failures, notes=notes, blocked=blocked, counts=counts,
                requires_model=True, denominator=0,
                denominator_note="实际评审条数（缺回复与评审未作答不计入分母）",
                rubric_version=BLIND_RUBRIC_VERSION)
        if blocked:
            return blocked_metric(
                "风格盲测", "≥80% 识别率",
                f"评审通道不可用，{len(blocked)} 条用例没能得出结论。",
                blocked=blocked, requires_model=True,
                rubric_version=BLIND_RUBRIC_VERSION)
        return skipped_metric(
            "风格盲测", "≥80% 识别率",
            f"没有可用的评审结果（{len(notes)} 条未作答）。",
            notes=notes, blocked=blocked, counts=counts,
            requires_model=True, rubric_version=BLIND_RUBRIC_VERSION)

    ratio = correct / checked
    detail = (f"共评审 {checked} 条回复，每个风格 3 条，覆盖全部 21 个风格。"
              f"分母 = 实际评审条数（{checked}）。")
    if notes:
        detail += f" 另有 {len(notes)} 条未计入（缺回复或评审未作答）。"
    if blocked:
        detail += f" 另有 {len(blocked)} 条被阻塞（评审通道出错）。"
    return metric(
        "风格盲测",
        "≥80% 识别率",
        f"{ratio * 100:.1f}%（{correct}/{checked}）",
        ratio >= 0.80,
        detail=detail,
        failures=failures,
        notes=notes,
        blocked=blocked,
        counts=counts,
        requires_model=True,
        denominator=checked,
        denominator_note="实际评审条数（缺回复与未作答不计入分母）",
        rubric_version=BLIND_RUBRIC_VERSION,
    )
