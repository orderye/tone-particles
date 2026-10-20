"""把判分结果渲染成对照 PRD 通过线的报告。"""

from __future__ import annotations

import json
from pathlib import Path

PASS = "✅ 通过"
FAIL = "❌ 未达标"
SKIP = "⏭️ 未评测"


def _detail_line(entry: dict) -> str:
    case_id = entry.get("case_id") or entry.get("scenario") or entry.get("style") or ""
    reason = entry.get("reason") or entry.get("detail") or ""
    extra = entry.get("type") or entry.get("expected") or ""
    parts = [part for part in (extra, reason) if part]
    head = f"`{case_id}`" if case_id else "（无编号）"
    return f"- {head} {'｜'.join(parts)}" if parts else f"- {head}"


def render(metrics: list, meta: dict | None = None) -> str:
    meta = meta or {}
    lines = ["# 语气助词 Skill 评测报告", ""]

    if meta:
        lines.append("## 运行信息")
        lines.append("")
        for key, value in meta.items():
            lines.append(f"- {key}：{value}")
        lines.append("")

    lines.append("## 指标对照")
    lines.append("")
    lines.append("| 指标 | PRD 通过线 | 实测 | 结果 |")
    lines.append("| --- | --- | --- | --- |")
    for item in metrics:
        if item.get("skipped"):
            status = SKIP
        elif item.get("passed"):
            status = PASS
        else:
            status = FAIL
        lines.append(
            f"| {item['metric']} | {item['threshold']} | {item['value']} | {status} |"
        )
    lines.append("")

    evaluated = [item for item in metrics if not item.get("skipped")]
    passed = [item for item in evaluated if item.get("passed")]
    lines.append(
        f"共 {len(metrics)} 项指标：{len(passed)}/{len(evaluated)} 项达标，"
        f"{len(metrics) - len(evaluated)} 项未评测。"
    )
    lines.append("")

    for item in metrics:
        if item.get("detail"):
            lines.append(f"### {item['metric']}")
            lines.append("")
            lines.append(item["detail"])
            lines.append("")

        # 未通过明细是真违规；未计入明细是测量缺口（缺回复、未作答、长度不足），
        # 两者分开渲染，别把「没测到」显示成「没达标」。
        for label, entries in (
            ("未通过明细", item.get("failures") or []),
            ("未计入明细", item.get("notes") or []),
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


def save(metrics: list, path, meta: dict | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(metrics, meta), encoding="utf-8")
    payload = {"meta": meta or {}, "metrics": metrics}
    path.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
