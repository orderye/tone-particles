#!/usr/bin/env python3
"""按用户配置抽取本轮风格。

用法：
    python3 scripts/pick_style.py config/user-config.json '["S01","S09"]'
    python3 scripts/pick_style.py config/user-config.json '["S01"]' --seed 42 --pretty
    python3 scripts/pick_style.py --config config/user-config.json --history-file .tone-history.json
    python3 scripts/pick_style.py --catalog

输出 JSON：
    {"mode": "...", "main": "S09", "accents": ["S04"],
     "main_name": "傲娇", "accent_names": ["邻家"],
     "history": ["S01", "S09"], "notes": []}

随机性由本脚本完成，模型只负责按结果表达；同一 seed + history 结果可复现。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: E402  本地模块，需先补 sys.path


def print_catalog() -> None:
    data, index = _core.load_catalog()
    entries = _core.catalog_entries(data, index)
    groups = {}
    for item in entries:
        groups.setdefault(item["group"], []).append(item)
    for group in data.get("groups", list(groups)):
        print(f"{group}")
        for item in groups.get(group, []):
            print(f"  {item['id']} {item['name']}：{item['one_liner']}")
        print()


def simulation_note(cfg: dict) -> str:
    if cfg["mode"] in {"single", "blend"}:
        return "single / blend 模式本就不随机，重复次数不具参考意义。"
    window = cfg["switch"].get("no_repeat_window", 3)
    if len(cfg["styles"]) <= window:
        return ("池不大于去重窗口，已放宽为仅避免连续重复；"
                "「零重复」与「权重精确」不可兼得，偏差可能超过 5%。")
    return "池大于去重窗口，零连续重复且权重偏差通常小于 5%。"


def simulate(cfg: dict, runs: int, seed=None) -> dict:
    """模拟多次抽样，统计连续重复与权重偏差。"""
    history = []
    counts = Counter()
    consecutive = 0
    previous = None
    for index in range(runs):
        result = _core.pick(cfg, history, seed=None if seed is None else seed + index)
        main = result["main"]
        if main == previous:
            consecutive += 1
        previous = main
        counts[main] += 1
        history = result["history"]
        # 只保留尾部，避免历史无限增长
        if len(history) > 50:
            history = history[-50:]

    total_weight = sum(item["weight"] for item in cfg["styles"])
    expected = {item["id"]: item["weight"] / total_weight for item in cfg["styles"]}
    observed = {sid: count / runs for sid, count in counts.items()}
    deviations = {
        sid: round(observed.get(sid, 0) - expected.get(sid, 0), 4)
        for sid in expected
    }
    max_deviation = max((abs(value) for value in deviations.values()), default=0)
    return {
        "runs": runs,
        "mode": cfg["mode"],
        "counts": dict(counts.most_common()),
        "expected_share": {sid: round(value, 4) for sid, value in expected.items()},
        "observed_share": {sid: round(value, 4) for sid, value in observed.items()},
        "deviation": deviations,
        "max_abs_deviation": round(max_deviation, 4),
        "consecutive_repeats": consecutive,
        "note": simulation_note(cfg),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="按配置抽取本轮语气风格")
    parser.add_argument("config", nargs="?", help="user-config.json 路径")
    parser.add_argument("history", nargs="?", help="历史风格 id 的 JSON 数组，如 '[\"S01\"]'")
    parser.add_argument("--config", dest="config_opt", help="同位置参数 config")
    parser.add_argument("--history", dest="history_opt", help="同位置参数 history")
    parser.add_argument("--history-file", help="从文件读取历史数组")
    parser.add_argument("--append-history", action="store_true",
                        help="把本轮结果写回 --history-file，供下一轮使用")
    parser.add_argument("--seed", type=int, default=None, help="随机种子，便于复现")
    parser.add_argument("--pretty", action="store_true", help="缩进输出")
    parser.add_argument("--catalog", action="store_true", help="打印 21 风格目录")
    parser.add_argument("--simulate", type=int, default=0, metavar="N",
                        help="模拟 N 次抽样，统计连续重复与权重偏差（仅 rotate / blend_random 有意义）")
    args = parser.parse_args(argv)

    if args.catalog:
        print_catalog()
        return 0

    config_path = args.config_opt or args.config
    cfg = _core.load_config(config_path)

    history = []
    raw_history = args.history_opt or args.history
    if args.history_file:
        history = _core.load_json(Path(args.history_file), label="配置文件", fallback=[])
    elif raw_history:
        try:
            history = json.loads(raw_history)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"history 不是合法 JSON：{exc}")
    if not isinstance(history, list):
        raise SystemExit("history 必须是 JSON 数组。")

    if args.simulate:
        stats = simulate(cfg, args.simulate, args.seed)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    result = _core.enrich(_core.pick(cfg, history, seed=args.seed), _core.load_catalog()[1])

    if args.append_history:
        if not args.history_file:
            raise SystemExit("--append-history 需要配合 --history-file 使用。")
        _core.save_history(Path(args.history_file), result["history"])

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
