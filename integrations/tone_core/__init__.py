"""宿主侧接入包。

把 skill 的核心能力包成一层稳定的 Python API：核心实现只有一份
（skill 目录下的 scripts/_core.py），这里只做转发与补齐，避免宿主适配层、
MCP 服务、命令行三处各写一套而漂移。

用法：

    import sys
    sys.path.insert(0, "integrations")
    from tone_core import ToneHost
"""

from __future__ import annotations

import sys
from pathlib import Path

# skill 包的根目录（integrations/ 的上一级）
SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _core  # noqa: E402
import check_density  # noqa: E402
import compose_prompt  # noqa: E402
import pick_style  # noqa: E402

from _core import (  # noqa: E402,F401
    GRANULARITIES,
    MODES,
    advance_turn,
    conflict_note,
    density_factor,
    density_range,
    extract_kaomoji_library,
    format_range,
    kaomoji_budget,
    load_catalog,
    load_config,
    load_json,
    load_particles,
    migrate_config,
    normalize_config,
    parse_style_sections,
    pick,
    save_config,
    style_text,
    validate_style_ids,
)
from compose_prompt import compose  # noqa: E402,F401

__all__ = [
    "GRANULARITIES",
    "MODES",
    "SKILL_ROOT",
    "advance_turn",
    "check_density",
    "compose",
    "compose_prompt",
    "conflict_note",
    "density_factor",
    "density_range",
    "extract_kaomoji_library",
    "format_range",
    "kaomoji_budget",
    "load_catalog",
    "load_config",
    "load_json",
    "load_particles",
    "migrate_config",
    "normalize_config",
    "parse_style_sections",
    "pick",
    "pick_style",
    "save_config",
    "style_text",
    "validate_style_ids",
]
