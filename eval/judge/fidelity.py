"""内容保真指标。

PRD 通过线：100%——去掉语气后与无风格版本信息等价。

做法分两步，都交给评审模型：
1. 让模型把回复里的语气词、口头禅、颜文字、角色腔调全部剥掉，只留信息本身。
2. 让模型判断剥完之后的信息是否完整回答了用户的问题、有没有被改写走样。

没有评审后端时标记 skipped。
"""

from __future__ import annotations

from .common import answered, metric, missing_replies, skipped_metric

STRIP_PROMPT = (
    "把下面这段回复里的语气成分全部去掉：语气助词、口头禅、颜文字、emoji、"
    "角色腔调、称呼自称的变化。\n"
    "只保留信息本身：结论、事实、步骤、代码、表格、数字。\n"
    "不要增删任何信息，也不要改写措辞。只输出剥离后的正文。"
)

FIDELITY_RUBRIC = """
判断给定的「去语气正文」是否完整、忠实地回答了用户的问题。

检查三件事：
1. 关键信息有没有丢（结论、步骤、条件、数据、代码）。
2. 有没有新增原文里没有的说法。
3. 数字、代码、专有名词有没有被改动。

只要丢信息或改动了事实，就算不等价。

只输出 JSON：{"equivalent": true 或 false, "missing": ["缺什么"], "changed": ["改了什么"]}
"""


def judge(responses: dict, cases: dict, backend=None) -> dict:
    if backend is None:
        return skipped_metric("内容保真", "100% 等价", "未配置评审后端。")
    ok, reason = backend.available()
    if not ok:
        return skipped_metric("内容保真", "100% 等价", f"评审后端不可用：{reason}")
    if not getattr(backend, "can_generate", False):
        # 保真判定分两步：先让模型剥掉语气，再判等价。档案/人工后端做不了第一步。
        return skipped_metric(
            "内容保真", "100% 等价",
            f"{getattr(backend, 'name', backend)} 后端不支持模型调用（无法剥语气），"
            "内容保真需要 chat_completions / messages_api。",
        )

    checked = 0
    equivalent = 0
    failures = []
    notes = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        plain = backend.generate(STRIP_PROMPT, reply).strip()
        verdict = backend.judge(FIDELITY_RUBRIC, {
            "case_id": case["id"],
            "user_input": case.get("user_input", ""),
            "original": reply,
            "plain": plain,
        })
        if not answered(verdict, "equivalent"):
            # 评审没给出「是否等价」的结论（如档案里没有该条的评审记录）
            # ＝没测到，不是不达标
            notes.append({"case_id": case["id"], "reason": "评审未给出结论，未计入"})
            continue
        checked += 1
        if verdict["equivalent"] is True:
            equivalent += 1
        else:
            failures.append({
                "case_id": case["id"],
                "reason": "；".join(
                    verdict.get("missing", []) + verdict.get("changed", [])
                ) or "评审判定不等价",
            })

    if checked == 0:
        return skipped_metric(
            "内容保真", "100% 等价",
            f"没有可用的评审结果（{len(notes)} 条未作答）。",
        )

    ratio = equivalent / checked
    detail = f"共评审 {checked} 条回复，先剥语气再比对信息完整性。"
    if missing:
        detail += f" 另有 {len(missing)} 条用例缺回复，未计入。"
    return metric(
        "内容保真",
        "100% 等价",
        f"{ratio * 100:.1f}%（{equivalent}/{checked}）",
        ratio >= 1.0,
        detail=detail,
        failures=failures,
        notes=notes,
    )
