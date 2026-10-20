#!/usr/bin/env python3
"""scripts/_core.py 的单元测试（纯标准库）。

覆盖：配置归一与迁移、抽样（可复现 / 去重窗口 / blend / single）、轮次状态机
五条路径、密度区间、风格文件解析、配置读写与 patch 合并、资源根切换。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import Runner  # noqa: E402

import _core  # noqa: E402


def base_config(**overrides) -> dict:
    cfg = {
        "mode": "rotate",
        "styles": [{"id": "S09", "weight": 3}, {"id": "S04", "weight": 2}, {"id": "S17", "weight": 1}],
        "density": "standard",
    }
    cfg.update(overrides)
    return _core.normalize_config(_core.migrate_config(cfg))


def main() -> int:
    r = Runner("核心函数 _core")

    # -- normalize / migrate -------------------------------------------------
    cfg = _core.normalize_config({"mode": "single", "styles": ["s09", "S04"]})
    r.check("str 风格项归一为 dict、去重后 single 截断",
            cfg["styles"] == [{"id": "S09", "weight": 1}], str(cfg["styles"]))
    cfg = _core.normalize_config({"mode": "single", "styles": [{"id": "s09", "weight": 2}]})
    r.check("风格 id 转大写且保留权重", cfg["styles"] == [{"id": "S09", "weight": 2}])
    r.check("switch.turns 默认 3", cfg["switch"]["turns"] == 3)
    r.check("kaomoji 默认补全", cfg["kaomoji"] == {"enabled": False, "level": "light"})

    r.raises("权重必须为正数", lambda: _core.normalize_config(
        {"mode": "single", "styles": [{"id": "S09", "weight": 0}]}), contains="权重必须为正数")
    r.raises("未知 mode 报错", lambda: _core.normalize_config(
        {"mode": "hourly", "styles": [{"id": "S09"}]}), contains="mode")
    r.raises("未知 granularity 报错", lambda: _core.normalize_config(
        {"mode": "single", "styles": [{"id": "S09"}], "switch": {"granularity": "hourly"}}),
        contains="granularity")
    r.raises("kaomoji.level 校验", lambda: _core.normalize_config(
        {"mode": "single", "styles": [{"id": "S09"}], "kaomoji": {"level": "huge"}}),
        contains="kaomoji.level")
    r.raises("migrate 拒绝过高版本", lambda: _core.migrate_config({"version": 99}),
             contains="高于当前支持")
    r.check("migrate 归一到当前版本",
            _core.migrate_config({"version": 1})["version"] == _core.DEFAULT_CONFIG_VERSION)

    # -- pick ----------------------------------------------------------------
    cfg = base_config()
    first = _core.pick(cfg, [], seed=42)
    second = _core.pick(cfg, [], seed=42)
    r.check("同一 seed 可复现", first == second)
    r.check("pick 把结果记入 history", first["history"] == [first["main"]])
    r.check("池不大于去重窗口时给出放宽说明",
            any("去重窗口" in note for note in first["notes"]), str(first["notes"]))

    wide = base_config(styles=[{"id": sid, "weight": 1} for sid in
                               ["S01", "S04", "S05", "S09", "S12", "S17"]])
    history = []
    repeats = 0
    for index in range(200):
        result = _core.pick(wide, history, seed=index)
        if history and result["main"] == history[-1]:
            repeats += 1
        history = result["history"]
    r.check("池大于窗口时无连续重复", repeats == 0, f"{repeats} 次重复")

    single = _core.pick(base_config(mode="single", styles=[{"id": "S09", "weight": 5}]), [], seed=1)
    r.check("single 模式只给主风格", single["main"] == "S09" and single["accents"] == [])

    blend = _core.pick(base_config(mode="blend"), [], seed=1)
    r.check("blend 主风格取最高权重", blend["main"] == "S09", blend["main"])
    r.check("blend 副风格最多 2 个", len(blend["accents"]) <= 2)

    low_main = _core.pick(base_config(
        mode="blend",
        styles=[{"id": "S09", "weight": 2}, {"id": "S04", "weight": 2}, {"id": "S17", "weight": 1}]),
        [], seed=1)
    r.check("主风格权重不足 50% 时给提示",
            any("50%" in note for note in low_main["notes"]), str(low_main["notes"]))

    # -- advance_turn --------------------------------------------------------
    state = {"history": [], "current": None, "turn": 0, "topic": None}
    decision = _core.advance_turn(state, base_config(), topic="工作", seed=7)
    r.check("首轮一定抽样", decision["switched"] is True and decision["active"] is True)
    state = decision["state"]

    locked_cfg = base_config(switch={"locked": True})
    decision = _core.advance_turn(state, locked_cfg, topic="别的", seed=7)
    r.check("locked 沿用当前风格",
            decision["switched"] is False and decision["main"] == state["current"]["main"])
    r.check("locked 给出说明", any("locked" in note for note in decision["notes"]))

    paused_cfg = base_config(paused=True)
    decision = _core.advance_turn(state, paused_cfg, topic="工作", seed=7)
    r.check("paused 时 active=False 且不注入", decision["active"] is False)
    r.check("paused 仍推进轮次", decision["state"]["turn"] == state["turn"] + 1)

    n_turns_cfg = base_config(switch={"granularity": "per_n_turns", "turns": 3})
    decision = _core.advance_turn({**state, "turn": 1}, n_turns_cfg, topic="工作", seed=7)
    r.check("per_n_turns 未到切换点沿用", decision["switched"] is False)
    decision = _core.advance_turn({**state, "turn": 3}, n_turns_cfg, topic="工作", seed=7)
    r.check("per_n_turns 到切换点重抽", decision["switched"] is True)

    topic_cfg = base_config(switch={"granularity": "on_topic_change"})
    decision = _core.advance_turn({**state, "topic": "工作"}, topic_cfg, topic="工作", seed=7)
    r.check("on_topic_change 话题不变则沿用", decision["switched"] is False)
    decision = _core.advance_turn({**state, "topic": "工作"}, topic_cfg, topic="周末", seed=7)
    r.check("on_topic_change 话题变化则重抽", decision["switched"] is True)

    session_cfg = base_config(switch={"granularity": "per_session"})
    decision = _core.advance_turn(state, session_cfg, topic="工作", seed=7)
    r.check("per_session 会话内不重抽", decision["switched"] is False)

    # -- 密度与解析 -----------------------------------------------------------
    members = [{"density": [2, 3]}, {"density": [4, 4]}]
    r.check("密度区间按权重加权",
            _core.density_range(members, [3, 1], 1.0) == (2.5, 3.25),
            str(_core.density_range(members, [3, 1], 1.0)))
    r.check("light 档减半", _core.density_factor("light") == 0.5)
    r.raises("未知密度档位报错", lambda: _core.density_factor("max"), contains="density")
    r.check("format_range 单值不带区间", _core.format_range(2.0, 2.0) == "2.0")
    r.check("format_range 区间格式", _core.format_range(1.0, 2.0) == "1.0–2.0")

    meta = _core.load_catalog()[1]["S01"]
    text = _core.style_text(meta)
    r.check("解析出签名元素", "反问收尾" in _core.extract_signature(text))
    r.check("解析出颜文字库", len(_core.extract_kaomoji_library(text)) >= 1)
    r.check("解析出定位", _core.extract_positioning(text) != "")

    # -- 配置读写与 patch ------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cfg_path = tmp_path / "user-config.json"

        cfg = _core.load_config(cfg_path)
        r.check("配置缺失时回退 defaults", cfg["mode"] == "single")
        r.raises("关闭回退时配置缺失报错", lambda: _core.load_config(
            tmp_path / "nope.json", fallback_defaults=False), contains="找不到配置文件")

        _core.save_config(cfg_path, cfg)
        r.check("save_config 落盘可回读", _core.load_config(cfg_path)["mode"] == "single")

        patched = _core.apply_config_patch(dict(cfg), {
            "density": "light", "switch": {"turns": 5}, "styles": ["s09"], "paused": None,
        })
        patched = _core.normalize_config(_core.migrate_config(patched))
        r.check("patch 覆盖标量键", patched["density"] == "light")
        r.check("patch 合并 dict 键", patched["switch"]["turns"] == 5
                and patched["switch"]["granularity"] == "per_message")
        r.check("patch 接受 str 风格项", patched["styles"] == [{"id": "S09", "weight": 1}])
        r.raises("patch 拒绝未知键", lambda: _core.apply_config_patch(
            dict(cfg), {"denstiy": "light"}), contains="未知配置键")

        history_path = tmp_path / "history.json"
        _core.save_history(history_path, [f"S{index:02d}" for index in range(60)])
        saved = json.loads(history_path.read_text(encoding="utf-8"))
        r.check("save_history 只留最近 50 条", len(saved) == 50 and saved[-1] == "S59")

    # -- 成员权重与资源根 ------------------------------------------------------
    cfg = base_config()
    r.check("members_with_weights 按配置配权",
            _core.members_with_weights(cfg, ["S09", "S04"]) == [("S09", 3), ("S04", 2)])
    r.check("单成员权重恒为 1",
            _core.members_with_weights(cfg, ["S09"]) == [("S09", 1)])

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config").mkdir()
        json.dump({"mode": "blend", "styles": [{"id": "S01"}, {"id": "S02"}]},
                  (root / "config" / "defaults.json").open("w", encoding="utf-8"))
        try:
            _core.set_resource_root(root)
            r.check("set_resource_root 后 defaults 从新根读取",
                    _core.load_config()["mode"] == "blend")
        finally:
            _core.set_resource_root(None)
        r.check("清除覆盖后回到默认根", _core.skill_root() == _core._DEFAULT_ROOT)

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
