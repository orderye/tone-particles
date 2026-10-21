"""内容保真指标。

PRD 通过线：100%——去掉语气后与无风格版本信息等价。

做法分两步，都交给评审模型：
1. 让模型把回复里的语气词、口头禅、颜文字、角色腔调全部剥掉，只留信息本身。
2. 让模型判断剥完之后的信息是否完整回答了用户的问题、有没有被改写走样。

**运行时边界（必须如实披露）：** 本系统的主要形式是把风格说明加入 system
prompt，并不是拿到一条「无风格回复」之后再做确定性文本变换。因此在真实运行时
里，系统手上并没有同一条问题对应的无风格基线回复，运行时无法做真正的双文本
语义比对。这里的判定发生在**评测环境**：它比较的是「原回复」与「从原回复里
剥掉语气后的版本」，验证的是「去掉语气不丢信息」，而不是「有风格的回复与一条
从未生成过的无风格回复语义一致」。后者需要额外的一次无风格生成（成本翻倍、
参数难以完全对齐），属于可选能力，不在默认调用链里。

评审过程出错（网络失败、HTTP 错误、返回格式不对）记为「被阻塞」；剥不出正文
（模型返回空）同样记为「被阻塞」——没法比的东西不算「不达标」。
"""

from __future__ import annotations

from .common import (
    answered,
    blocked_metric,
    call_judge,
    metric,
    missing_replies,
    skipped_metric,
)

FIDELITY_RUBRIC_VERSION = "fidelity-v1"

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

RUNTIME_BOUNDARY = (
    "运行时边界：真实运行时系统没有同一条问题的无风格基线回复（风格是加进 "
    "system prompt 的），因此无法在运行时做双文本语义比对。本指标在评测环境里"
    "比较「原回复」与「剥掉语气后的正文」，验证的是去掉语气不丢信息。"
)


def judge(responses: dict, cases: dict, backend=None) -> dict:
    if backend is None:
        return skipped_metric("内容保真", "100% 等价", "未配置评审后端。",
                              requires_model=True, rubric_version=FIDELITY_RUBRIC_VERSION)
    ok, reason = backend.available()
    if not ok:
        return skipped_metric("内容保真", "100% 等价", f"评审后端不可用：{reason}",
                              requires_model=True, rubric_version=FIDELITY_RUBRIC_VERSION)
    if not getattr(backend, "can_generate", False):
        # 保真判定分两步：先让模型剥掉语气，再判等价。档案/人工后端做不了第一步。
        return skipped_metric(
            "内容保真", "100% 等价",
            f"{getattr(backend, 'name', backend)} 后端不支持模型调用（无法剥语气），"
            "内容保真需要 chat_completions / messages_api。",
            requires_model=True, rubric_version=FIDELITY_RUBRIC_VERSION)

    checked = 0
    equivalent = 0
    failures = []
    notes = []
    blocked = []
    missing = missing_replies(cases, responses)

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        if reply is None:
            continue
        try:
            plain = backend.generate(STRIP_PROMPT, reply).strip()
        except (Exception, SystemExit) as exc:
            blocked.append({
                "case_id": case["id"],
                "reason": f"剥语气失败：{type(exc).__name__}: {exc}",
            })
            continue
        if not plain:
            blocked.append({
                "case_id": case["id"],
                "reason": "剥语气后没有正文，无法比对。",
            })
            continue
        verdict, blocked_reason = call_judge(backend, FIDELITY_RUBRIC, {
            "case_id": case["id"],
            "user_input": case.get("user_input", ""),
            "original": reply,
            "plain": plain,
        })
        if blocked_reason:
            blocked.append({"case_id": case["id"], "reason": blocked_reason})
            continue
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

    for case_id in missing:
        notes.append({"case_id": case_id, "reason": "缺回复，未计入"})

    counts = {
        "passed": equivalent,
        "failed": len(failures),
        "not_evaluated": len(notes),
        "blocked": len(blocked),
        "denominator": checked,
    }

    if checked == 0:
        if blocked:
            return blocked_metric(
                "内容保真", "100% 等价",
                f"评审通道不可用，{len(blocked)} 条用例没能得出结论。",
                blocked=blocked, requires_model=True,
                rubric_version=FIDELITY_RUBRIC_VERSION)
        return skipped_metric(
            "内容保真", "100% 等价",
            f"没有可用的评审结果（{len(notes)} 条未作答）。",
            notes=notes, blocked=blocked, counts=counts,
            requires_model=True, rubric_version=FIDELITY_RUBRIC_VERSION)

    ratio = equivalent / checked
    detail = (f"共评审 {checked} 条回复，先剥语气再比对信息完整性。"
              f"分母 = 实际评审条数（{checked}）。{RUNTIME_BOUNDARY}")
    if notes:
        detail += f" 另有 {len(notes)} 条未计入。"
    if blocked:
        detail += f" 另有 {len(blocked)} 条被阻塞。"
    return metric(
        "内容保真",
        "100% 等价",
        f"{ratio * 100:.1f}%（{equivalent}/{checked}）",
        ratio >= 1.0,
        detail=detail,
        failures=failures,
        notes=notes,
        blocked=blocked,
        counts=counts,
        requires_model=True,
        denominator=checked,
        denominator_note="实际评审条数（缺回复、剥不出正文、评审未作答不计入分母）",
        rubric_version=FIDELITY_RUBRIC_VERSION,
    )
