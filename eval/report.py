"""把判分结果渲染成对照 PRD 通过线的报告。"""

from __future__ import annotations

import json
from pathlib import Path

PASS = "✅ 通过"
FAIL = "❌ 未达标"
SKIP = "⏭️ 未评测"


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

        failures = item.get("failures") or []
        if not failures:
            continue
        lines.append(f"#### {item['metric']} · 未通过明细（{len(failures)}）")
        lines.append("")
        for failure in failures[:40]:
            case_id = failure.get("case_id") or failure.get("scenario") or failure.get("style") or ""
            reason = failure.get("reason") or failure.get("detail") or ""
            extra = failure.get("type") or failure.get("expected") or ""
            parts = [part for part in (extra, reason) if part]
            lines.append(f"- `{case_id}` {'｜'.join(parts)}")
        if len(failures) > 40:
            lines.append(f"- …另有 {len(failures) - 40} 条")
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
