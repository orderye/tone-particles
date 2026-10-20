"""风格盲测指标。

PRD 通过线：≥80%。每个风格 ≥3 条回复，评审从 21 个选项中盲选。

评审只拿到「用户输入 + 回复」和 21 个候选风格（顺序按固定种子打乱，保证可复现），
不告诉它这条本来该是哪种风格。没有模型后端时可用人工盲测表录入，
或直接标记为 skipped。
"""

from __future__ import annotations

import hashlib
import random

from .common import answered, catalog, metric, missing_replies, skipped_metric, style_meta

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
        return skipped_metric("风格盲测", "≥80% 识别率", "未配置评审后端。")
    ok, reason = backend.available()
    if not ok:
        return skipped_metric("风格盲测", "≥80% 识别率", f"评审后端不可用：{reason}")

    pool = cases.get("pool", [])
    checked = 0
    correct = 0
    failures = []
    notes = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        prompt = pool[case["prompt"]] if pool else case.get("user_input", "")
        options = _options(_stable_seed(case["id"]))
        meta = style_meta(case["style"])
        expected = f"{meta['id']} {meta['name']}"

        verdict = backend.judge(BLIND_RUBRIC, {
            "case_id": case["id"],
            "display": f"【用户输入】\n{prompt}\n\n【回复】\n{reply}",
            "options": options,
        })

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

    if checked == 0:
        return skipped_metric(
            "风格盲测", "≥80% 识别率",
            f"没有可用的评审结果（{len(notes)} 条未作答）。",
        )

    ratio = correct / checked
    detail = f"共评审 {checked} 条回复，每个风格 3 条，覆盖全部 21 个风格。"
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        "风格盲测",
        "≥80% 识别率",
        f"{ratio * 100:.1f}%（{correct}/{checked}）",
        ratio >= 0.80,
        detail=detail,
        failures=failures,
        notes=notes,
    )
