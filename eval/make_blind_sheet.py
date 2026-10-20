#!/usr/bin/env python3
"""生成人工盲测表。

候选风格的顺序与 judge/blind.py 里的一致（同一个稳定种子），所以人工填的
结论能直接被 `--backend fixture` 读回来判分。

用法：
    python3 eval/make_blind_sheet.py            # 写到 eval/blind_sheet.md
    python3 eval/make_blind_sheet.py --out 路径
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from judge.blind import _options, _stable_seed  # noqa: E402
from judge.common import load_cases, load_responses  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成人工盲测表")
    parser.add_argument("--out", help="输出路径，默认 eval/blind_sheet.md")
    parser.add_argument("--responses", help="回复目录，默认 eval/fixtures/responses")
    args = parser.parse_args(argv)

    cases = load_cases("blind")
    pool = cases.get("pool", [])
    responses = load_responses(args.responses)

    lines = [
        "# 人工盲测表",
        "",
        "每条只看「回复」，从 21 个候选里选出最接近的一种。",
        "只看表达层：措辞、句式、口头禅、称呼自称、情绪强度。不要评价内容质量。",
        "",
        "把结论写成 `eval/fixtures/judgments/<用例 id>.json`，内容形如：",
        "",
        "```json",
        '{"choice": "S09 傲娇"}',
        "```",
        "",
        "写好后用 `python3 eval/run.py --backend fixture` 判分。",
        "",
        "---",
        "",
    ]

    for case in cases["cases"]:
        reply = responses.get(case["id"])
        prompt = pool[case["prompt"]] if pool else case.get("user_input", "")
        lines.append(f"## {case['id']}")
        lines.append("")
        lines.append("**用户输入**")
        lines.append("")
        lines.append(f"> {prompt}")
        lines.append("")
        lines.append("**回复**")
        lines.append("")
        if reply:
            lines.append("> " + reply.replace("\n", "\n> ").strip())
        else:
            lines.append("> （暂无回复，请先补齐 `fixtures/responses/"
                         f"{case['id']}.md`）")
        lines.append("")
        lines.append("**候选**")
        lines.append("")
        for option in _options(_stable_seed(case["id"])):
            lines.append(f"- [ ] {option}")
        lines.append("")
        lines.append("**结论**：`______`")
        lines.append("")
        lines.append("---")
        lines.append("")

    out = Path(args.out) if args.out else EVAL_ROOT / "blind_sheet.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"盲测表已写入 {out}（{len(cases['cases'])} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
