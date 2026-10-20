"""MCP 工具的入参 schema。

用 JSON Schema 描述，客户端据此渲染调用表单。schema 同时是运行时校验的依据：
server.py 会按这里声明的必填项与类型做基本检查。
"""

from __future__ import annotations

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
            "enum": ["light", "standard", "strong"],
            "description": "密度档位，默认 standard。",
        },
        "variant": {
            "type": "string",
            "enum": ["gentle", "strict"],
            "description": "老师风格（S20）的子模式：gentle 温柔型 / strict 严厉型。",
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
            "enum": ["single", "blend", "rotate", "blend_random"],
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
            "enum": ["light", "standard", "strong"],
        },
        "switch": {
            "type": "object",
            "properties": {
                "granularity": {
                    "type": "string",
                    "enum": ["per_message", "per_n_turns", "on_topic_change", "per_session"],
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
                "level": {"type": "string", "enum": ["light", "normal"]},
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
