"""MCP 工具实现。

四个工具对应 PRD 8.1 的方案 C：list_styles / get_style_prompt / set_user_style /
pick_next_style。

实现直接调用 skill 的核心纯函数，不经过命令行子进程——没有额外延迟，
也绕开了 CLI 层「未知风格 id 静默通过」这类契约缺口。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _core  # noqa: E402
import compose_prompt  # noqa: E402

DEFAULT_CONFIG = SKILL_ROOT / "config" / "user-config.json"
DEFAULTS_PATH = SKILL_ROOT / "config" / "defaults.json"


class Tools:
    """四个 MCP 工具。config_path 指向当前用户的配置。"""

    def __init__(self, config_path=None, root=None):
        self.root = Path(root) if root else SKILL_ROOT
        self.config_path = Path(config_path) if config_path else (
            self.root / "config" / "user-config.json")
        self._catalog = None

    # -- 内部 -----------------------------------------------------------

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = _core.load_catalog()
        return self._catalog

    def _config(self) -> dict:
        path = self.config_path if self.config_path.exists() else DEFAULTS_PATH
        if not path.exists():
            raise ValueError(f"找不到配置文件：{self.config_path}")
        raw = _core.load_json(path, label="配置文件")
        return _core.normalize_config(_core.migrate_config(raw))

    # -- 工具 -----------------------------------------------------------

    def list_styles(self, group=None, include_prompt=False):
        """列出 21 个风格。"""
        data, index = self.catalog
        groups = data.get("groups", [])
        items = []
        for meta in index.values():
            if group and meta.get("group") != group:
                continue
            entry = {
                "id": meta["id"],
                "name": meta["name"],
                "group": meta.get("group"),
                "one_liner": meta.get("one_liner"),
                "vector": meta.get("vector"),
                "density": meta.get("density"),
                "kaomoji": meta.get("kaomoji"),
                "signature": meta.get("signature", []),
            }
            if include_prompt:
                entry["prompt"] = _core.style_text(meta)
            items.append(entry)
        return {"groups": groups, "count": len(items), "styles": items}

    def get_style_prompt(self, style_id, accents=None, weights=None, density=None, variant=None):
        """生成单一或融合风格的提示词。"""
        ids = [str(style_id).upper()]
        ids.extend(str(accent).upper() for accent in (accents or []))
        if weights:
            weights = [int(item) for item in weights]
            if len(weights) != len(ids):
                raise ValueError(
                    f"weights 的长度（{len(weights)}）与风格数量（{len(ids)}）不一致。")
        else:
            weights = None
        members = [(sid, 1) for sid in ids]
        variants = {"S20": variant} if variant else None
        return compose_prompt.compose(members, weights, density or "standard", variants)

    def set_user_style(self, **patch):
        """写入用户配置。"""
        cfg = self._config()
        for key, value in patch.items():
            if value is None:
                continue
            if key in ("switch", "kaomoji") and isinstance(value, dict):
                cfg.setdefault(key, {}).update(value)
            elif key == "styles":
                cleaned = []
                for item in value:
                    if isinstance(item, str):
                        item = {"id": item, "weight": 1}
                    cleaned.append({
                        "id": str(item["id"]).upper(),
                        "weight": int(item.get("weight", 1)),
                    })
                cfg["styles"] = cleaned
            else:
                cfg[key] = value
        cfg = _core.normalize_config(_core.migrate_config(cfg))
        _core.save_config(self.config_path, cfg)
        return {
            "saved": True,
            "config_path": str(self.config_path),
            "config": cfg,
        }

    def pick_next_style(self, history=None, seed=None):
        """按当前配置抽取本轮风格。"""
        cfg = self._config()
        result = _core.pick(cfg, history or [], seed=seed)
        catalog = self.catalog[1]
        main = result["main"]
        if main not in catalog:
            raise ValueError(
                f"未知风格 id：{main}。可用：{', '.join(sorted(catalog))}")
        result["main_name"] = catalog[main]["name"]
        result["accent_names"] = [
            catalog[sid]["name"] for sid in result["accents"] if sid in catalog
        ]
        result["mode"] = cfg["mode"]
        return result


TOOL_DESCRIPTIONS = {
    "list_styles": "列出语气助词 Skill 的 21 个风格，含分组、气质描述、向量、密度区间与签名元素。",
    "get_style_prompt": "生成某个风格（或主风格 + 副风格融合）的提示词，可直接追加到 system prompt 末尾。",
    "set_user_style": "设置用户的语气偏好：运行模式、风格池、密度档位、切换粒度、颜文字开关、是否暂停。",
    "pick_next_style": "按当前配置随机抽取本轮风格，带去重窗口，同一 seed 与 history 可复现。",
}

DISPATCH = {
    "list_styles": lambda tools, args: tools.list_styles(
        group=args.get("group"),
        include_prompt=bool(args.get("include_prompt")),
    ),
    "get_style_prompt": lambda tools, args: tools.get_style_prompt(
        style_id=args["style_id"],
        accents=args.get("accents"),
        weights=args.get("weights"),
        density=args.get("density"),
        variant=args.get("variant"),
    ),
    "set_user_style": lambda tools, args: tools.set_user_style(
        **{key: value for key, value in args.items()}
    ),
    "pick_next_style": lambda tools, args: tools.pick_next_style(
        history=args.get("history"),
        seed=args.get("seed"),
    ),
}


def call_tool(tools: Tools, name: str, arguments: dict) -> str:
    """执行一个工具，返回给客户端的文本内容。"""
    handler = DISPATCH.get(name)
    if handler is None:
        raise ValueError(f"未知工具：{name}")
    result = handler(tools, arguments or {})
    return json.dumps(result, ensure_ascii=False, indent=2)
