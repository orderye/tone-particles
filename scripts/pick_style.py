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
import random
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_PATH = SKILL_ROOT / "config" / "defaults.json"
STYLES_PATH = SKILL_ROOT / "config" / "styles.json"

MODES = {"single", "blend", "rotate", "blend_random"}


def load_json(path: Path, fallback=None):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if fallback is not None:
            return fallback
        raise SystemExit(f"找不到配置文件：{path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"配置文件不是合法 JSON：{path}（{exc}）")


def load_catalog():
    if not STYLES_PATH.exists():
        return {}
    data = load_json(STYLES_PATH)
    return {item["id"]: item for item in data.get("styles", [])}


def normalize(cfg: dict) -> dict:
    """补默认值并做基本校验。"""
    if not isinstance(cfg, dict):
        raise SystemExit("配置必须是 JSON 对象。")

    cfg.setdefault("mode", "single")
    cfg.setdefault("styles", [])
    cfg.setdefault("density", "standard")
    cfg.setdefault("switch", {})
    if not isinstance(cfg["switch"], dict):
        cfg["switch"] = {}
    cfg["switch"].setdefault("granularity", "per_message")
    cfg["switch"].setdefault("no_repeat_window", 3)
    cfg["switch"].setdefault("locked", False)
    cfg.setdefault("paused", False)

    if cfg["mode"] not in MODES:
        raise SystemExit(f"mode 必须是 {sorted(MODES)} 之一，当前为 {cfg['mode']!r}。")
    if not isinstance(cfg["styles"], list) or not cfg["styles"]:
        raise SystemExit("styles 至少要有 1 项。")

    cleaned = []
    seen = set()
    for item in cfg["styles"]:
        if isinstance(item, str):
            item = {"id": item, "weight": 1}
        if not isinstance(item, dict) or "id" not in item:
            raise SystemExit(f"styles 项格式不对：{item!r}")
        sid = str(item["id"]).upper()
        if sid in seen:
            continue
        seen.add(sid)
        weight = item.get("weight", 1)
        try:
            weight = int(weight)
        except (TypeError, ValueError):
            raise SystemExit(f"权重必须是整数：{item!r}")
        if weight <= 0:
            raise SystemExit(f"权重必须为正数：{item!r}")
        cleaned.append({"id": sid, "weight": weight})
    cfg["styles"] = cleaned

    if cfg["mode"] == "single" and len(cleaned) != 1:
        cfg["styles"] = cleaned[:1]

    window = cfg["switch"].get("no_repeat_window", 3)
    try:
        window = int(window)
    except (TypeError, ValueError):
        raise SystemExit("switch.no_repeat_window 必须是整数。")
    cfg["switch"]["no_repeat_window"] = max(0, min(window, 10))
    return cfg


def weighted_choice(pairs, rng):
    ids = [item[0] for item in pairs]
    weights = [item[1] for item in pairs]
    return rng.choices(ids, weights=weights, k=1)[0]


def banned_set(pool, history, window):
    if window <= 0 or len(pool) <= 1:
        return set()
    # 池子不够大时放宽为「仅避免连续重复」，否则强制轮转会让权重失效
    effective = window if len(pool) > window else 1
    return set(history[-effective:]) if effective > 0 else set()


def pick(cfg: dict, history=None, seed=None) -> dict:
    history = [str(item).upper() for item in (history or [])]
    rng = random.Random(seed)
    pool = [(item["id"], item["weight"]) for item in cfg["styles"]]
    mode = cfg["mode"]
    notes = []

    if mode == "single":
        return {
            "mode": mode,
            "main": pool[0][0],
            "accents": [],
            "history": history + [pool[0][0]],
            "notes": notes,
        }

    if mode == "blend":
        ranked = sorted(pool, key=lambda item: item[1], reverse=True)
        main = ranked[0][0]
        accents = [item[0] for item in ranked[1:3]]
        total = sum(item[1] for item in ranked)
        if ranked[0][1] / total < 0.5:
            notes.append("主风格权重不足 50%，已按最高权重指定主风格。")
        return {
            "mode": mode,
            "main": main,
            "accents": accents,
            "history": history + [main],
            "notes": notes,
        }

    window = cfg["switch"].get("no_repeat_window", 3)
    if 0 < window and len(pool) <= window:
        notes.append("池不大于去重窗口，已放宽为仅避免连续重复；权重优先。")
    banned = banned_set(pool, history, window)
    candidates = [item for item in pool if item[0] not in banned] or pool
    main = weighted_choice(candidates, rng)

    accents = []
    if mode == "blend_random" and len(pool) > 1 and rng.random() < 0.5:
        rest = [item for item in pool if item[0] != main]
        accents = [weighted_choice(rest, rng)]

    return {
        "mode": mode,
        "main": main,
        "accents": accents,
        "history": history + [main],
        "notes": notes,
    }


def enrich(result: dict) -> dict:
    catalog = load_catalog()
    main = result["main"]
    result["main_name"] = catalog.get(main, {}).get("name", main)
    result["accent_names"] = [
        catalog.get(sid, {}).get("name", sid) for sid in result["accents"]
    ]
    return result


def print_catalog() -> None:
    if not STYLES_PATH.exists():
        raise SystemExit(f"找不到 {STYLES_PATH}")
    data = load_json(STYLES_PATH)
    groups = {}
    for item in data["styles"]:
        groups.setdefault(item["group"], []).append(item)
    for group in data.get("groups", list(groups)):
        print(f"{group}")
        for item in groups.get(group, []):
            print(f"  {item['id']} {item['name']}：{item['one_liner']}")
        print()


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
    if config_path:
        cfg = load_json(Path(config_path))
    elif DEFAULTS_PATH.exists():
        cfg = load_json(DEFAULTS_PATH)
    else:
        raise SystemExit("没有指定配置，且找不到 config/defaults.json。")
    cfg = normalize(cfg)

    history = []
    raw_history = args.history_opt or args.history
    if args.history_file:
        history = load_json(Path(args.history_file), fallback=[])
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

    result = enrich(pick(cfg, history, seed=args.seed))

    if args.append_history:
        if not args.history_file:
            raise SystemExit("--append-history 需要配合 --history-file 使用。")
        save_history(Path(args.history_file), result["history"])

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


def save_history(path: Path, history) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(history[-50:], ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def simulate(cfg: dict, runs: int, seed=None) -> dict:
    """模拟多次抽样，统计连续重复与权重偏差。"""
    from collections import Counter

    history = []
    counts = Counter()
    consecutive = 0
    previous = None
    for index in range(runs):
        result = pick(cfg, history, seed=None if seed is None else seed + index)
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


def simulation_note(cfg: dict) -> str:
    if cfg["mode"] in {"single", "blend"}:
        return "single / blend 模式本就不随机，重复次数不具参考意义。"
    window = cfg["switch"].get("no_repeat_window", 3)
    if len(cfg["styles"]) <= window:
        return ("池不大于去重窗口，已放宽为仅避免连续重复；"
                "「零重复」与「权重精确」不可兼得，偏差可能超过 5%。")
    return "池大于去重窗口，零连续重复且权重偏差通常小于 5%。"


if __name__ == "__main__":
    sys.exit(main())
