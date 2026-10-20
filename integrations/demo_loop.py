#!/usr/bin/env python3
"""端到端演示：把宿主适配层跑起来看看。

用一个假模型顶替真实模型，只验证「宿主 → 适配层 → 提示词 → 回检」这条链路通不通：
每轮打印选中的风格、注入的 system 后缀长度、密度区间，以及回检结果。

用法：
    python3 integrations/demo_loop.py
    python3 integrations/demo_loop.py --mode rotate --seed 7
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from host_adapter import ToneHost  # noqa: E402
from tone_core import MODES  # noqa: E402

TURNS = [
    ("最近工作忙得脚不沾地，连周末都在加班。", "工作"),
    ("帮我想想周末去哪儿走走比较好。", "周末"),
    ("那天气热的话要注意什么？", "周末"),
]


def fake_reply(user_input: str) -> str:
    """假模型：返回一段带语气助词的固定回复，够回检用。"""
    return (
        "嗯，这个我帮你看看吧。其实吧，先把最要紧的那件拎出来，"
        "剩下的按顺序排一下就行了。你要是还有别的想法，"
        "我们再一起对一对呢。"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="宿主适配层端到端演示")
    parser.add_argument("--mode", default="blend_random", choices=sorted(MODES))
    parser.add_argument("--styles", default="S09:3,S04:2,S17:1",
                        help="风格池，形如 S09:3,S04:2")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--keep", action="store_true", help="保留临时配置目录")
    args = parser.parse_args(argv)

    styles = []
    for chunk in args.styles.split(","):
        sid, _, weight = chunk.partition(":")
        styles.append({"id": sid.strip(), "weight": int(weight or 1)})

    workdir = Path(tempfile.mkdtemp(prefix="tone-demo-"))
    config_path = workdir / "user-config.json"
    history_path = workdir / "tone-history.json"
    config_path.write_text(json.dumps({
        "version": 1,
        "mode": args.mode,
        "styles": styles,
        "density": "standard",
        "switch": {"granularity": "per_message", "no_repeat_window": 3, "locked": False},
        "scene_adapt": True,
        "kaomoji": {"enabled": False, "level": "light"},
        "emoji": "style_default",
        "paused": False,
        "variants": {},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    host = ToneHost(config_path=config_path, history_path=history_path, seed=args.seed)
    host.begin_session()

    print(f"配置：{config_path}")
    print(f"模式：{args.mode}    风格池：{args.styles}\n")

    first_suffix = ""
    for index, (user_input, topic) in enumerate(TURNS, start=1):
        turn = host.next_turn(user_input, topic=topic)
        if not turn["active"]:
            print(f"── 第 {index} 轮：语气已暂停，不注入任何风格\n")
            continue
        if not first_suffix:
            first_suffix = turn["system_suffix"]

        reply = fake_reply(user_input)
        check = host.observe(reply)

        names = "、".join(
            f"{m['id']} {m['name']}" + ("（主）" if m["role"] == "main" else "（副）")
            for m in turn["members"]
        )
        print(f"── 第 {index} 轮")
        print(f"   话题　　　：{topic}")
        print(f"   本轮风格　：{names}")
        print(f"   是否切换　：{'是' if turn.get('switched') else '否（沿用）'}")
        print(f"   密度区间　：{turn['density_range']} 次/百字")
        print(f"   注入后缀　：{len(turn['system_suffix'])} 字符")
        print(f"   回检密度　：{check['modal_per_100']} 次/百字（目标 {check['target']}，"
              f"{check['target_status']}）")
        print(f"   规则问题　：{[v['type'] for v in check['violations']] or '无'}")
        for note in turn["notes"]:
            print(f"   提示　　　：{note}")
        print()

    print("注入内容预览（第一轮）：")
    print("-" * 60)
    print("\n".join(first_suffix.splitlines()[:12]))
    print("-" * 60)

    if args.keep:
        print(f"\n临时目录已保留：{workdir}")
    else:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
