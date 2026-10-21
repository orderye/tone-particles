"""把判分结果渲染成对照 PRD 通过线的报告。

报告里有四种状态，含义不同，不能混：

- 通过：跑了，而且达标。
- 未达标：跑了，而且不达标。
- 未评测：没跑成——没有后端、缺回复、评审没作答。这是**测量缺口**。
- 被阻塞：评测过程本身出错（网络、HTTP、返回格式不对）。这是**系统故障**。

「未评测」既不是通过也不是不达标。把没测到的东西渲染成「❌ 未达标」会让人
以为内容有问题；渲染成「✅ 通过」更糟——那是在说谎。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from judge.common import (  # noqa: E402
    STATUS_BLOCKED,
    STATUS_FAILED,
    STATUS_LABEL,
    STATUS_NOT_EVALUATED,
    STATUS_PASSED,
)

# 报告格式的版本。字段含义变了要能看出来。
REPORT_SCHEMA_VERSION = 2

PASS = f"✅ {STATUS_LABEL[STATUS_PASSED]}"
FAIL = f"❌ {STATUS_LABEL[STATUS_FAILED]}"
SKIP = f"⏭️ {STATUS_LABEL[STATUS_NOT_EVALUATED]}"
BLOCKED = f"⛔ {STATUS_LABEL[STATUS_BLOCKED]}"


def _status_label(status: str) -> str:
    return {
        STATUS_PASSED: PASS,
        STATUS_FAILED: FAIL,
        STATUS_NOT_EVALUATED: SKIP,
        STATUS_BLOCKED: BLOCKED,
    }.get(status, STATUS_LABEL.get(status, status))


def _detail_line(entry: dict) -> str:
    case_id = entry.get("case_id") or entry.get("scenario") or entry.get("style") or ""
    reason = entry.get("reason") or entry.get("detail") or ""
    extra = entry.get("type") or entry.get("expected") or ""
    parts = [part for part in (extra, reason) if part]
    head = f"`{case_id}`" if case_id else "（无编号）"
    return f"- {head} {'｜'.join(parts)}" if parts else f"- {head}"


def _summary(metrics: list) -> dict:
    summary = {STATUS_PASSED: 0, STATUS_FAILED: 0,
               STATUS_NOT_EVALUATED: 0, STATUS_BLOCKED: 0}
    for item in metrics:
        status = item.get("status")
        if status is None:
            # 兼容没有 status 字段的旧指标
            status = (STATUS_NOT_EVALUATED if item.get("skipped")
                      else STATUS_PASSED if item.get("passed") else STATUS_FAILED)
        summary[status] = summary.get(status, 0) + 1
    return summary


def render(metrics: list, meta: dict | None = None, verdict: dict | None = None) -> str:
    meta = meta or {}
    summary = _summary(metrics)
    lines = ["# 语气助词 Skill 评测报告", ""]
    lines.append(f"报告 schema 版本：{REPORT_SCHEMA_VERSION}")
    lines.append("")

    if meta:
        lines.append("## 运行信息")
        lines.append("")
        for key, value in meta.items():
            if isinstance(value, dict):
                lines.append(f"- {key}：")
                for sub_key, sub_value in value.items():
                    lines.append(f"    - {sub_key}：{sub_value}")
            else:
                lines.append(f"- {key}：{value}")
        lines.append("")

    lines.append("## 总览")
    lines.append("")
    lines.append(
        f"共 {len(metrics)} 项指标：通过 {summary[STATUS_PASSED]} 项，"
        f"未达标 {summary[STATUS_FAILED]} 项，"
        f"未评测 {summary[STATUS_NOT_EVALUATED]} 项，"
        f"被阻塞 {summary[STATUS_BLOCKED]} 项。"
    )
    lines.append("")
    lines.append(
        "「未评测」与「被阻塞」都不是通过：前者是没跑成（缺后端、缺回复、评审没作答），"
        "后者是评测过程出错。"
    )
    lines.append("")

    lines.append("## 指标对照")
    lines.append("")
    lines.append("| 指标 | PRD 通过线 | 实测 | 状态 | 分母 | 需要模型 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in metrics:
        status = item.get("status")
        if status is None:
            status = (STATUS_NOT_EVALUATED if item.get("skipped")
                      else STATUS_PASSED if item.get("passed") else STATUS_FAILED)
        counts = item.get("counts") or {}
        denominator = counts.get("denominator")
        denominator_text = (
            f"{denominator}" if denominator is not None
            else (str(item.get("denominator")) if item.get("denominator") is not None else "—"))
        lines.append(
            f"| {item['metric']} | {item['threshold']} | {item['value']} | "
            f"{_status_label(status)} | {denominator_text} | "
            f"{'是' if item.get('requires_model') else '否'} |"
        )
    lines.append("")

    if verdict:
        lines.append("## 发布阻断项")
        lines.append("")
        blockers = []
        for item in verdict.get("failed", []):
            blockers.append(f"{item['metric']}：未达标")
        for item in verdict.get("blocked", []):
            blockers.append(f"{item['metric']}：被阻塞（评测过程出错，结论缺失）")
        if verdict.get("strict"):
            for item in verdict.get("model_pending", []):
                blockers.append(f"{item['metric']}：模型类指标未评测（严格模式下阻断发布）")
            for item in verdict.get("other_pending", []):
                blockers.append(f"{item['metric']}：未评测（严格模式下阻断发布）")
        if blockers:
            for item in blockers:
                lines.append(f"- {item}")
        else:
            lines.append("- 无")
        if not verdict.get("strict"):
            pending = verdict.get("model_pending", []) + verdict.get("other_pending", [])
            if pending:
                lines.append("")
                lines.append(
                    "另有 "
                    + "、".join(f"「{item['metric']}」" for item in pending)
                    + " 处于「未评测」状态。未评测不是通过：本次运行没有得出结论，"
                    "发布候选验收前必须补上（`--strict` 会因此返回退出码 2）。"
                )
        lines.append("")

    for item in metrics:
        if item.get("detail"):
            lines.append(f"### {item['metric']}")
            lines.append("")
            lines.append(item["detail"])
            counts = item.get("counts") or {}
            if counts:
                lines.append("")
                lines.append(
                    f"计数：通过 {counts.get('passed', 0)}、未达标 {counts.get('failed', 0)}、"
                    f"未评测 {counts.get('not_evaluated', 0)}、被阻塞 {counts.get('blocked', 0)}；"
                    f"分母 {counts.get('denominator', '—')}"
                    + (f"（{item.get('denominator_note')}）" if item.get("denominator_note") else "")
                )
            if item.get("rubric_version"):
                lines.append("")
                lines.append(f"判分标准版本：{item['rubric_version']}")
            lines.append("")

        # 三类明细分开渲染：真违规、测量缺口、系统故障。
        for label, entries in (
            ("未通过明细", item.get("failures") or []),
            ("未计入明细", item.get("notes") or []),
            ("被阻塞明细", item.get("blocked") or []),
        ):
            if not entries:
                continue
            lines.append(f"#### {item['metric']} · {label}（{len(entries)}）")
            lines.append("")
            for entry in entries[:40]:
                lines.append(_detail_line(entry))
            if len(entries) > 40:
                lines.append(f"- …另有 {len(entries) - 40} 条")
            lines.append("")

    return "\n".join(lines)


def save(metrics: list, path, meta: dict | None = None, verdict: dict | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(metrics, meta, verdict), encoding="utf-8")
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "meta": meta or {},
        "metrics": metrics,
        "verdict": verdict or {},
    }
    path.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
