#!/usr/bin/env python3
"""宿主适配层的 JSON over stdio 版本。

给非 Python 宿主（Node / Go / Rust / Shell）用：宿主每次往 stdin 写一行 JSON，
本进程回一行 JSON。

    {"op": "next_turn", "user_input": "帮我安排明天的日程", "topic": "日程"}
    {"op": "observe", "reply": "模型回复正文"}
    {"op": "set_config", "patch": {"mode": "single", "styles": [{"id": "S09", "weight": 1}]}}
    {"op": "get_state"}

每行响应形如 {"ok": true, "result": {...}} 或 {"ok": false, "error": "..."}。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from host_adapter import ToneHost  # noqa: E402
from tone_core import catalog_entries, load_catalog  # noqa: E402


def handle(host: ToneHost, request: dict) -> dict:
    op = request.get("op")
    if op == "begin_session":
        return host.begin_session()
    if op == "next_turn":
        return host.next_turn(
            request.get("user_input", ""),
            topic=request.get("topic"),
            density=request.get("density"),
            context=request.get("context"),
        )
    if op == "observe":
        return host.observe(
            request.get("reply", ""),
            style=request.get("style"),
            density=request.get("density"),
        )
    if op == "set_config":
        return host.update_config(request.get("patch") or {})
    if op == "get_state":
        return host.get_state()
    if op == "catalog":
        data, index = load_catalog()
        return {
            "groups": data.get("groups", []),
            "styles": catalog_entries(data, index),
        }
    raise SystemExit(f"未知操作：{op!r}。可用：begin_session / next_turn / observe / "
                     "set_config / get_state / catalog")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="语气助词的宿主适配层（JSON over stdio）")
    parser.add_argument("--config", help="用户配置路径")
    parser.add_argument("--history", help="历史文件路径")
    parser.add_argument("--root", help="skill 根目录，默认自动定位")
    parser.add_argument("--seed", type=int, default=None, help="随机种子，便于复现")
    args = parser.parse_args(argv)

    host = ToneHost(
        config_path=args.config,
        history_path=args.history,
        root=args.root,
        seed=args.seed,
    )
    host.begin_session()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = {"ok": True, "result": handle(host, request)}
        except SystemExit as exc:
            response = {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - 宿主侧不应因单次请求崩掉
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
