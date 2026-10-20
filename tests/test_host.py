#!/usr/bin/env python3
"""integrations/host_adapter.py 的行为测试（纯标准库）。

重点回归：配置里的权重必须进入提示词配比——曾经的 bug 是把 None 传给
compose()，触发默认 4:2:2，让宿主路径（4:2:2）与 CLI 路径（3:2:1）不一致。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import ROOT, Runner  # noqa: E402

sys.path.insert(0, str(ROOT / "integrations"))

import _core  # noqa: E402
from host_adapter import ToneHost  # noqa: E402


def write_config(path: Path, **overrides) -> None:
    cfg = {
        "version": 1,
        "mode": "blend",
        "styles": [{"id": "S09", "weight": 3}, {"id": "S04", "weight": 2}, {"id": "S17", "weight": 1}],
        "density": "standard",
    }
    cfg.update(overrides)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    r = Runner("宿主适配层 ToneHost")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "user-config.json"
        history_path = tmp_path / "tone-history.json"
        write_config(config_path)

        host = ToneHost(config_path=config_path, history_path=history_path, seed=7)
        r.check("配置存在时不要求导入向导", host.onboarding_required is False)
        host.begin_session()
        turn = host.next_turn("帮我看看这段代码", topic="代码")

        members = [(item["id"], item["weight"]) for item in turn["members"]]
        r.check("配置权重进入提示词配比（回归）",
                members == [("S09", 3), ("S04", 2), ("S17", 1)], str(members))
        r.check("share 与权重一致（50/33/17）",
                [item["share"] for item in turn["members"]] == [0.5, 0.333, 0.167],
                str([item["share"] for item in turn["members"]]))
        r.check("提示词写出配比",
                "50%" in turn["system_suffix"] and "33%" in turn["system_suffix"])
        r.check("本轮返回主风格与向量", turn["style"] == "S09" and "vector" in turn)
        r.check("历史落盘", history_path.exists())
        saved_history = json.loads(history_path.read_text(encoding="utf-8"))
        r.check("历史记录本轮主风格", saved_history == ["S09"], str(saved_history))

        updated = host.update_config({"density": "light", "switch": {"locked": True}})
        r.check("update_config 覆盖标量键", updated["density"] == "light")
        r.check("update_config 合并 dict 键",
                updated["switch"]["locked"] is True, str(updated["switch"]))
        r.raises("update_config 拒绝未知键",
                 lambda: host.update_config({"denstiy": "light"}), contains="未知配置键")

        check = host.observe("嗯，这个我帮你看看吧，剩下的按顺序排一下就行了呢。")
        r.check("observe 返回密度与目标", "modal_per_100" in check and check["target"])
        r.check("observe 返回硬规则结果", isinstance(check["violations"], list))

        bad = host.observe("好呀呀呀，我们走吧。")
        r.check("observe 能报助词堆叠",
                any("堆叠" in item["type"] for item in bad["violations"]),
                str(bad["violations"]))

        state = host.get_state()
        r.check("get_state 带轮次与路径",
                state["turn"] == 1 and state["config_path"] == str(config_path), str(state))

        # 损坏的历史文件不应让会话起不来
        history_path.write_text("{ not json", encoding="utf-8")
        fresh = ToneHost(config_path=config_path, history_path=history_path, seed=7)
        info = fresh.begin_session()
        r.check("损坏历史被容忍", info["history"] == 0)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config").mkdir()
        try:
            host = ToneHost(root=root)
            r.check("root 参数成为资源根", _core.skill_root() == root.resolve())
            r.check("root 参与默认路径拼接",
                    host.config_path == root.resolve() / "config" / "user-config.json",
                    str(host.config_path))
            r.check("此时要求导入向导", host.onboarding_required is True)
        finally:
            _core.set_resource_root(None)

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
