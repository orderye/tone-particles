#!/usr/bin/env python3
"""安全硬规则的机器化回归（纯标准库）。

把 references/safety.md 里可判定的规则变成断言，避免「文档改了、测试没改」：

1. safety.md 第 9 节的红队表与 eval/cases/redteam.json 一一对应
2. safety.md 第 1 节禁用关系位 / 宠物化的称呼，确实进了词表的禁用词
3. 禁用词确实会被 check_density 检出（不是写在文档里就算数）
4. 任何风格、任何融合组合（含冲突风格）生成的提示词都带着安全段落
5. SKILL.md 声明安全边界优先于风格

运行：python3 tests/test_safety.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import ROOT, Runner  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

import _core  # noqa: E402
import check_density  # noqa: E402
import compose_prompt  # noqa: E402

SAFETY_MD = ROOT / "references" / "safety.md"
REDTEAM_JSON = ROOT / "eval" / "cases" / "redteam.json"
SKILL_MD = ROOT / "SKILL.md"


def safety_text() -> str:
    return SAFETY_MD.read_text(encoding="utf-8")


def redteam_table_rows() -> list:
    """取 safety.md 第 9 节表格的「期望」列。"""
    text = safety_text()
    section = text.split("## 9. 红队用例（验收）", 1)
    if len(section) < 2:
        return []
    rows = []
    for line in section[1].splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"用例", "---"} or set(cells[0]) == {"-"}:
            continue
        rows.append(cells[1])
    return rows


def main() -> int:
    r = Runner("安全硬规则")

    text = safety_text()
    cases = json.loads(REDTEAM_JSON.read_text(encoding="utf-8"))["cases"]
    reasons = [case.get("expect", {}).get("reason", "") for case in cases]

    # -- 1. 文档里的红队表与评测用例一致 ----------------------------------------
    rows = redteam_table_rows()
    r.check("safety.md 第 9 节有红队表", len(rows) >= 7, f"解析到 {len(rows)} 行")
    unmatched = [row for row in rows if not any(row in reason for reason in reasons)]
    r.check("每条红队表都有对应的评测用例", not unmatched, str(unmatched))
    r.check("红队用例不少于红队表",
            len(cases) >= len(rows), f"{len(cases)} 条用例 / {len(rows)} 行表")

    # -- 2. 关系位与宠物化称呼进了禁用词 ----------------------------------------
    particles = _core.load_particles()
    banned = set(particles.get("banned", []))
    quoted = re.findall(r"「([^」]+)」", text.split("## 2.")[0])
    required = {term for term in quoted if term in {
        "老公", "老婆", "宝宝", "亲爱的", "主人", "喵", "嘤", "嗷呜"}}
    missing = sorted(term for term in required if term not in banned)
    r.check("safety.md 明令禁用的称呼都在词表禁用词里",
            not missing, f"缺：{missing}")
    derived = {"哥哥", "爸爸", "妈妈"}
    missing_derived = sorted(term for term in derived if term not in banned)
    r.check("关系位称呼都在词表禁用词里", not missing_derived, f"缺：{missing_derived}")

    # -- 3. 禁用词确实会被检测器检出 --------------------------------------------
    undetected = []
    for word in sorted(banned):
        result = check_density.analyze(f"这是一句测试{word}的话。", None, False)
        if not any(item["type"] == check_density.VIOLATION_TYPES["banned"]
                   for item in result["violations"]):
            undetected.append(word)
    r.check("每个禁用词都能被 check_density 检出", not undetected, str(undetected))

    # -- 4. 提示词里的安全段落不会因风格或融合而丢失 ---------------------------
    catalog_data, index = _core.load_catalog()
    missing_safety = []
    for meta in index.values():
        payload = compose_prompt.compose([(meta["id"], 1)], None, "standard", None)
        if "安全边界" not in payload["prompt"] or "危机" not in payload["prompt"]:
            missing_safety.append(meta["id"])
    r.check("每个单一风格的提示词都带安全边界与危机处理",
            not missing_safety, str(missing_safety))

    conflict_pairs = catalog_data.get("conflict_pairs", [])
    missing_blend = []
    for pair in conflict_pairs:
        payload = compose_prompt.compose(
            [(pair[0], 4), (pair[1], 2)], [4, 2], "standard", None)
        prompt = payload["prompt"]
        if "## 通用规则（优先于风格）" not in prompt or "安全边界" not in prompt:
            missing_blend.append(tuple(pair))
    r.check("冲突风格融合后仍带安全段落",
            not missing_blend, str(missing_blend))

    multi = compose_prompt.compose(
        [(meta["id"], 4) for meta in list(index.values())[:3]], None, "strong", None)
    r.check("三风格融合也带安全段落",
            "安全边界" in multi["prompt"] and "references/safety.md" in multi["prompt"])
    r.check("融合提示词声明了安全优先",
            "优先于风格" in multi["prompt"])

    # -- 5. 危机红队必须要求求助渠道 --------------------------------------------
    crisis = [case for case in cases if "120" in json.dumps(case.get("expect", {}))]
    r.check("危机用例要求给出求助渠道", len(crisis) >= 1, f"{len(crisis)} 条")
    crisis_cases = [case for case in cases if case.get("expect", {}).get("style_off")]
    r.check("危机类用例要求完全关闭风格", len(crisis_cases) >= 1)

    # -- 6. SKILL.md 声明安全优先 ------------------------------------------------
    skill = SKILL_MD.read_text(encoding="utf-8")
    r.check("SKILL.md 声明安全边界优先于任何风格",
            "安全边界优先于任何风格" in skill)
    r.check("SKILL.md 指向 references/safety.md", "references/safety.md" in skill)

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
