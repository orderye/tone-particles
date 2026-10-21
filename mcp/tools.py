"""MCP 工具实现。

四个工具对应 PRD 8.1 的方案 C：list_styles / get_style_prompt / set_user_style /
pick_next_style。

实现直接调用 skill 的核心纯函数，不经过命令行子进程——没有额外延迟，校验与
报错口径也和 CLI（scripts/_core.py）共用同一份实现。
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


class Tools:
    """四个 MCP 工具。config_path 指向当前用户的配置。"""

    def __init__(self, config_path=None, root=None):
        if root:
            # --root 指向新的 skill 根：styles / particles / defaults 都从那里取
            _core.set_resource_root(root)
        self.root = _core.skill_root()
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
        return _core.load_config(self.config_path)

    # -- 工具 -----------------------------------------------------------

    def list_styles(self, group=None, include_prompt=False):
        """列出 21 个风格。"""
        data, index = self.catalog
        items = _core.catalog_entries(
            data, index, group=group, include_prompt=bool(include_prompt))
        return {"groups": data.get("groups", []), "count": len(items), "styles": items}

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
        """写入用户配置。未知键报错；值为 None 表示不改动。

        走共享核心的加锁「读—改—写」：写成功之后才返回，写失败（只读目录、
        并发冲突、校验不通过）一律报工具级错误，不返回「保存成功」。
        """
        cfg = _core.update_config_file(self.config_path, patch)
        return {
            "saved": True,
            "config_path": str(self.config_path),
            "config": cfg,
        }

    def pick_next_style(self, history=None, seed=None):
        """按当前配置抽取本轮风格。"""
        cfg = self._config()
        result = _core.pick(cfg, history or [], seed=seed)
        _core.enrich(result, self.catalog[1])
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
