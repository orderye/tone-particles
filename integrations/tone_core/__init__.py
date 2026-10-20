"""宿主侧接入包。

把 skill 的核心能力包成一层稳定的 Python API：核心实现只有一份
（skill 目录下的 scripts/_core.py），这里只做转发，避免宿主适配层、
MCP 服务、命令行三处各写一套而漂移。

用法：

    import sys
    sys.path.insert(0, "integrations")
    from tone_core import advance_turn, compose, load_config   # 核心函数
    from host_adapter import ToneHost                          # 参考宿主适配器
"""

from __future__ import annotations

import sys
from pathlib import Path

# 本包的安装位置（integrations/ 的上一级）；只用于把 scripts/ 加进 sys.path。
# 读取资源请用 _core 的 skill_root() / set_resource_root()，它们才反映当前资源根。
SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _core  # noqa: E402
import check_density  # noqa: E402

from _core import (  # noqa: E402,F401
    CONFIG_KEYS,
    GRANULARITIES,
    MODES,
    advance_turn,
    apply_config_patch,
    catalog_entries,
    conflict_note,
    density_factor,
    density_range,
    enrich,
    extract_kaomoji_library,
    format_range,
    kaomoji_budget,
    load_catalog,
    load_config,
    load_json,
    load_particles,
    members_with_weights,
    migrate_config,
    normalize_config,
    parse_style_sections,
    pick,
    save_config,
    save_history,
    set_resource_root,
    skill_root,
    style_text,
    validate_style_ids,
)
from compose_prompt import compose  # noqa: E402,F401

__all__ = [
    "CONFIG_KEYS",
    "GRANULARITIES",
    "MODES",
    "SKILL_ROOT",
    "advance_turn",
    "apply_config_patch",
    "catalog_entries",
    "check_density",
    "compose",
    "conflict_note",
    "density_factor",
    "density_range",
    "enrich",
    "extract_kaomoji_library",
    "format_range",
    "kaomoji_budget",
    "load_catalog",
    "load_config",
    "load_json",
    "load_particles",
    "members_with_weights",
    "migrate_config",
    "normalize_config",
    "parse_style_sections",
    "pick",
    "save_config",
    "save_history",
    "set_resource_root",
    "skill_root",
    "style_text",
    "validate_style_ids",
]
