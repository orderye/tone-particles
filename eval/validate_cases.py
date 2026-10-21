#!/usr/bin/env python3
"""评测用例的结构校验。

在评测开始前检查数据集本身有没有问题：重复 id、缺字段、非法风格 id、
非法 scene、题池索引越界、盲测集风格分布不均……

这些是**评测输入出错**，属于「被阻塞」，不是「被测内容不达标」——两者不能
混在同一个失败列表里。

用法：
    python3 eval/validate_cases.py          # 打印问题列表，有问题返回 1
    python3 eval/validate_cases.py --quiet  # 只看退出码
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVAL_ROOT.parent
CASES_DIR = EVAL_ROOT / "cases"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import _core  # noqa: E402

CASE_FILES = ["chats", "blind", "fusion", "redteam", "scenes"]
KNOWN_SCENES = {
    "normal", "code", "table", "high_risk", "error_steps",
    "low_mood", "crisis", "formal", "non_chinese",
}


def _catalog_ids() -> set:
    return set(_core.load_catalog()[1])


def _check_anchors(case_id: str, case: dict, problems: list) -> None:
    for field in ("anchors", "forbidden_anchors"):
        value = case.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value):
            problems.append(f"{case_id}: {field} 必须是非空字符串组成的列表")


def validate_all(cases_dir=None) -> list:
    """返回问题列表；空列表表示数据集结构完好。"""
    base = Path(cases_dir) if cases_dir else CASES_DIR
    problems: list = []
    catalog_ids = _catalog_ids()
    seen_ids: dict = {}

    for name in CASE_FILES:
        path = base / f"{name}.json"
        if not path.exists():
            problems.append(f"缺少用例文件：{path.name}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name} 不是合法 JSON：{exc}")
            continue
        cases = data.get("cases")
        if not isinstance(cases, list) or not cases:
            problems.append(f"{path.name}: cases 必须是非空列表")
            continue
        if "version" not in data:
            problems.append(f"{path.name}: 缺少 version 字段")

        for case in cases:
            case_id = case.get("id")
            if not case_id:
                problems.append(f"{path.name}: 有用例缺少 id")
                continue
            if case_id in seen_ids:
                problems.append(
                    f"用例 id 重复：{case_id}（{seen_ids[case_id]} 与 {path.name}）")
            seen_ids[case_id] = path.name

            for field in ("style", "main", "accent"):
                sid = case.get(field)
                if sid is not None and sid not in catalog_ids:
                    problems.append(f"{case_id}: 未知风格 id {sid}")
            if case.get("main") and case.get("main") == case.get("accent"):
                problems.append(f"{case_id}: 主风格与副风格不能相同")

            scene = case.get("scene")
            if scene is not None and scene not in KNOWN_SCENES:
                problems.append(f"{case_id}: 未知 scene {scene!r}")

            min_chars = case.get("min_chars")
            if min_chars is not None and (
                    not isinstance(min_chars, int) or min_chars <= 0):
                problems.append(f"{case_id}: min_chars 必须是正整数")

            pool = data.get("pool")
            if "prompt" in case and isinstance(pool, list):
                prompt = case["prompt"]
                if not isinstance(prompt, int) or not 0 <= prompt < len(pool):
                    problems.append(
                        f"{case_id}: prompt 索引 {prompt!r} 越界（题池长度 {len(pool)}）")

            _check_anchors(case_id, case, problems)

            expect = case.get("expect")
            if expect is not None:
                if not isinstance(expect, dict):
                    problems.append(f"{case_id}: expect 必须是对象")
                else:
                    for field in ("must_match", "must_not_match"):
                        value = expect.get(field)
                        if value is not None and (
                                not isinstance(value, list)
                                or not all(isinstance(item, str) for item in value)):
                            problems.append(f"{case_id}: expect.{field} 必须是字符串列表")

            if name == "chats" and not case.get("user_input"):
                problems.append(f"{case_id}: 缺少 user_input")
            if name == "redteam" and not case.get("user_input"):
                problems.append(f"{case_id}: 缺少 user_input")

        if name == "blind":
            counts: dict = {}
            for case in cases:
                counts[case.get("style")] = counts.get(case.get("style"), 0) + 1
            missing = sorted(set(catalog_ids) - set(counts))
            if missing:
                problems.append(f"盲测集缺少风格：{'、'.join(missing)}")
            uneven = {sid: count for sid, count in counts.items() if count != 3}
            if uneven:
                problems.append(
                    "盲测集每个风格应恰好 3 条，实际："
                    + "、".join(f"{sid}={count}" for sid, count in sorted(uneven.items())))

    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="评测用例结构校验")
    parser.add_argument("--cases", help="用例目录，默认 eval/cases")
    parser.add_argument("--quiet", action="store_true", help="只返回退出码")
    args = parser.parse_args(argv)

    problems = validate_all(args.cases)
    if not problems:
        if not args.quiet:
            print(f"用例结构校验通过（{len(CASE_FILES)} 个用例文件）。")
        return 0
    print("用例结构校验发现 %d 个问题：" % len(problems), file=sys.stderr)
    for item in problems:
        print(f"  - {item}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
