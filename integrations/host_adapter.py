#!/usr/bin/env python3
"""参考宿主适配器。

把 skill 的「每轮流程」实现成宿主可以直接调用的一个对象：

    读配置 → 按切换粒度决定本轮风格 → 拼提示词 → 维护历史 → 写回配置

宿主只需要做两件事：
1. 每轮请求前调 `next_turn()`，把返回的 `system_suffix` 追加到 system prompt 末尾。
2. 模型回复后调 `observe()`，拿到密度与硬规则的回检结果（可选，用于埋点）。

多用户隔离：每个用户一份 config_path 与 history_path，互不干扰。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tone_core import (  # noqa: E402
    advance_turn,
    apply_config_patch,
    check_density,
    compose,
    load_catalog,
    load_config,
    load_json,
    members_with_weights,
    migrate_config,
    normalize_config,
    save_config,
    save_history,
    set_resource_root,
    skill_root,
)


class ToneHost:
    """一个用户（或一份会话）的语气状态机。"""

    def __init__(self, config_path=None, history_path=None, root=None, seed=None):
        if root:
            # root 的语义是「skill 根目录」：styles / particles / defaults 都从那里取
            set_resource_root(root)
        self.root = skill_root()
        self.config_path = Path(config_path) if config_path else (
            self.root / "config" / "user-config.json")
        self.history_path = Path(history_path) if history_path else (
            self.root / "config" / "tone-history.json")
        self.seed = seed
        self.state = {"history": [], "current": None, "turn": 0, "topic": None}
        self._catalog = None

    # -- 配置 -----------------------------------------------------------

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = load_catalog()
        return self._catalog

    @property
    def onboarding_required(self) -> bool:
        """配置不存在时为 True，宿主据此触发导入向导。"""
        return not self.config_path.exists()

    def load_config(self) -> dict:
        """读取用户配置；不存在时回退到 defaults.json。"""
        return load_config(self.config_path)

    def save_config(self, cfg: dict) -> None:
        save_config(self.config_path, cfg)

    # -- 会话 -----------------------------------------------------------

    def begin_session(self) -> dict:
        """会话开始时调用：载入历史，重置轮次计数。"""
        history = []
        if self.history_path.exists():
            try:
                history = load_json(self.history_path, label="配置文件", fallback=[])
            except SystemExit:
                history = []
        if not isinstance(history, list):
            history = []
        self.state = {"history": history, "current": None, "turn": 0, "topic": None}
        return {"history": len(history), "config": self.config_path.exists()}

    # -- 每轮 -----------------------------------------------------------

    def next_turn(self, user_input: str, topic=None, density=None) -> dict:
        """本轮要注入的 system 后缀。

        返回 {"active", "system_suffix", "style", "members", "density_range", "notes"}。
        `active` 为 False 时语气已暂停，system_suffix 为空串。
        """
        cfg = self.load_config()
        decision = advance_turn(self.state, cfg, topic=topic, seed=self.seed)
        self.state = decision["state"]

        if not decision["active"]:
            return {
                "active": False,
                "system_suffix": "",
                "style": None,
                "members": [],
                "density_range": None,
                "notes": decision["notes"],
            }

        members = members_with_weights(cfg, [decision["main"]] + decision["accents"])

        level = density or cfg.get("density", "standard")
        payload = compose(members, [weight for _, weight in members], level, cfg.get("variants"))

        save_history(self.history_path, decision["state"]["history"])
        return {
            "active": True,
            "system_suffix": payload["prompt"],
            "style": decision["main"],
            "style_name": payload["members"][0]["name"] if payload["members"] else None,
            "members": payload["members"],
            "vector": payload["vector"],
            "density": level,
            "density_range": payload["density_range"],
            "conflicts": payload["conflicts"],
            "switched": decision["switched"],
            "notes": decision["notes"],
        }

    def observe(self, reply_text: str, style=None, density=None) -> dict:
        """回填模型回复，返回密度与硬规则的回检结果。"""
        cfg = self.load_config()
        style_id = style or (self.state.get("current") or {}).get("main")
        level = density or cfg.get("density", "standard")
        kaomoji = cfg.get("kaomoji") or {}
        result = check_density.analyze(
            reply_text,
            style_id,
            False,
            density_level=level,
            kaomoji_enabled=bool(kaomoji.get("enabled")),
        )
        return {
            "style": result["style"],
            "chars": result["chars"],
            "modal_per_100": result["modal_per_100"],
            "target": result["target"],
            "target_status": result["target_status"],
            "kaomoji_count": result["kaomoji_count"],
            "violations": result["violations"],
            "ok": result["ok"],
        }

    def update_config(self, patch: dict) -> dict:
        """应用控制指令对应的配置变更并写回。未知键报错；None 表示不改动。"""
        cfg = self.load_config()
        apply_config_patch(cfg, patch)
        cfg = normalize_config(migrate_config(cfg))
        self.save_config(cfg)
        return cfg

    def get_state(self) -> dict:
        return {
            "turn": self.state.get("turn"),
            "current": self.state.get("current"),
            "history": list(self.state.get("history") or [])[-10:],
            "config_path": str(self.config_path),
            "onboarding_required": self.onboarding_required,
        }
