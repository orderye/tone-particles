"""MCP 工具的入参 schema。

用 JSON Schema 描述，客户端据此渲染调用表单。schema 同时是运行时校验的依据：
server.py 会按这里声明的必填项做检查，工具实现（tools.py）负责取值校验。

枚举一律从 scripts/_core.py 取，避免和核心的常量各写一份而漂移。
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _core  # noqa: E402
import _context  # noqa: E402

STYLE_ID = {"type": "string", "description": "风格 id，如 S09。共 21 个。"}
STYLE_ID_LIST = {
    "type": "array",
    "items": STYLE_ID,
    "maxItems": 2,
    "description": "副风格 id 列表，最多 2 个。",
}
WEIGHT_LIST = {
    "type": "array",
    "items": {"type": "integer", "minimum": 1},
    "description": "与 styles 一一对应的权重。",
}

LIST_STYLES = {
    "type": "object",
    "properties": {
        "group": {
            "type": "string",
            "description": "只返回该分组内的风格；不填返回全部。分组：成熟稳重 / 强势气场 / 软萌可爱 / 明亮活力 / 冷感神秘 / 反差古典。",
        },
        "include_prompt": {
            "type": "boolean",
            "description": "是否附带每个风格文件的全文。默认 false——全文约 1k tokens，21 个一起给会撑爆上下文。",
        },
    },
    "additionalProperties": False,
}

GET_STYLE_PROMPT = {
    "type": "object",
    "properties": {
        "style_id": STYLE_ID,
        "accents": STYLE_ID_LIST,
        "weights": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1},
            "description": "权重，第一个是主风格的，其余依次对应 accents。默认主 4、副 2。",
        },
        "density": {
            "type": "string",
            "enum": sorted(_core.DENSITY_FACTOR),
            "description": "密度档位，默认 standard。",
        },
        "variant": {
            "type": "string",
            "enum": ["gentle", "strict"],
            "description": "老师风格（S20）的子模式：gentle 温柔型 / strict 严厉型。",
        },
        "context": {
            "type": "object",
            "description": "可选的语境元数据，覆盖语境策略的自动检测。",
            "properties": {
                "scene": {
                    "type": "string",
                    "enum": sorted(_context.EXPLICIT_SCENES),
                    "description": "任务场景：闲聊 / 知识解释 / 代码排障 / 正式写作 / "
                                   "结构化输出 / 高风险 / 情绪低落 / 报错排查 / 非中文。",
                },
            },
            "additionalProperties": False,
        },
    },
    "required": ["style_id"],
    "additionalProperties": False,
}

SET_USER_STYLE = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": sorted(_core.MODES),
            "description": "运行模式。",
        },
        "styles": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": STYLE_ID,
                    "weight": {"type": "integer", "minimum": 1},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
            "description": "风格池。single 模式只需 1 项，其余模式 2–21 项。",
        },
        "density": {
            "type": "string",
            "enum": sorted(_core.DENSITY_FACTOR),
        },
        "switch": {
            "type": "object",
            "properties": {
                "granularity": {
                    "type": "string",
                    "enum": sorted(_core.GRANULARITIES),
                },
                "no_repeat_window": {"type": "integer", "minimum": 0, "maximum": 10},
                "locked": {"type": "boolean"},
                "turns": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "additionalProperties": False,
        },
        "kaomoji": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "level": {"type": "string", "enum": sorted(_core.KAOMOJI_LEVELS)},
            },
            "additionalProperties": False,
        },
        "paused": {"type": "boolean", "description": "暂停语气。"},
        "variants": {
            "type": "object",
            "description": "风格子模式，目前只有 S20 支持 gentle / strict。",
            "additionalProperties": {"type": "string"},
        },
    },
    "additionalProperties": False,
}

PICK_NEXT_STYLE = {
    "type": "object",
    "properties": {
        "history": {
            "type": "array",
            "items": STYLE_ID,
            "description": "最近用过的风格 id，用于去重。不填则不启用去重。",
        },
        "seed": {"type": "integer", "description": "随机种子，便于复现。"},
    },
    "additionalProperties": False,
}

SCHEMAS = {
    "list_styles": LIST_STYLES,
    "get_style_prompt": GET_STYLE_PROMPT,
    "set_user_style": SET_USER_STYLE,
    "pick_next_style": PICK_NEXT_STYLE,
}


# --------------------------------------------------------------------------
# 运行时校验
# --------------------------------------------------------------------------
#
# schema 不只是给客户端看的表单说明，也是服务端的校验依据。这里实现 schema 里
# 实际用到的那些关键字的子集，不追求通用 JSON Schema 实现。


def _type_ok(value, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _check_value(name: str, value, spec: dict) -> list:
    """校验单个参数值，返回错误信息列表。"""
    errors: list = []
    expected = spec.get("type")
    if expected and not _type_ok(value, expected):
        errors.append(f"参数 {name} 的类型应为 {expected}，实际为 {type(value).__name__}")
        return errors
    if "enum" in spec and value not in spec["enum"]:
        errors.append(
            f"参数 {name} 只能是 {sorted(spec['enum'], key=str)} 之一，当前为 {value!r}")
    if expected == "array":
        if "minItems" in spec and len(value) < spec["minItems"]:
            errors.append(f"参数 {name} 至少要有 {spec['minItems']} 项")
        if "maxItems" in spec and len(value) > spec["maxItems"]:
            errors.append(f"参数 {name} 最多 {spec['maxItems']} 项")
        item_spec = spec.get("items")
        if item_spec:
            for index, item in enumerate(value):
                errors.extend(_check_value(f"{name}[{index}]", item, item_spec))
    if expected == "object":
        properties = spec.get("properties") or {}
        if spec.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"参数 {name} 里出现了未知字段 {key!r}")
        for key, item in value.items():
            sub = properties.get(key)
            if sub:
                errors.extend(_check_value(f"{name}.{key}", item, sub))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            errors.append(f"参数 {name} 不能小于 {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            errors.append(f"参数 {name} 不能大于 {spec['maximum']}")
    return errors


def validate_arguments(schema: dict, arguments) -> tuple:
    """按 schema 校验工具参数。

    返回 (协议级错误, 未知参数)：
    - 协议级错误（类型、枚举、长度、越界、缺必填）→ JSON-RPC -32602。
    - 未知参数 → 工具级错误。既有契约里「未知配置键」是工具级错误
      （isError，模型能读到并自我纠正），这里保持不变，但不再静默丢弃。
    """
    if not isinstance(arguments, dict):
        return ["arguments 必须是 JSON 对象。"], []
    errors: list = []
    properties = schema.get("properties") or {}
    for key in schema.get("required", []):
        if key not in arguments:
            errors.append(f"缺少必填参数：{key}")
    unknown = [key for key in arguments if key not in properties]
    for key, value in arguments.items():
        spec = properties.get(key)
        if not spec or value is None:
            continue
        errors.extend(_check_value(key, value, spec))
    return errors, unknown
