#!/usr/bin/env python3
"""tone-particles 共享核心。

三个 CLI、宿主适配层与工具接口服务共用这一份实现：配置读写、风格目录、密度区间、
风格文件解析、抽样与轮次状态机都只在这里定义一次，避免同一套语义在多处漂移。

纯标准库，无第三方依赖。
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path

MODES = {"single", "blend", "rotate", "blend_random"}
GRANULARITIES = {"per_message", "per_n_turns", "on_topic_change", "per_session"}
DENSITY_FACTOR = {"light": 0.5, "standard": 1.0, "strong": 1.5}
DENSITY_LABEL = {"light": "轻", "standard": "标准", "strong": "浓"}
KAOMOJI_LEVELS = {"light", "normal"}
DEFAULT_CONFIG_VERSION = 1
# set_user_style / update_config 允许改写的配置键；其余一律报错，防止拼错静默落盘。
CONFIG_KEYS = {
    "mode", "styles", "density", "switch", "kaomoji",
    "paused", "variants", "emoji", "scene_adapt",
}


# --------------------------------------------------------------------------
# 资源根
# --------------------------------------------------------------------------

# styles / particles / defaults 这些随代码分发的资源所在目录。默认取本文件所在
# skill 树；把 skill 部署到别处时可以用 TONE_PARTICLES_ROOT 环境变量或
# set_resource_root() 重设。它是进程内全局：多用户隔离靠各自的 config /
# history 路径（config_path / history_path），不靠这里。
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent
_resource_root = None
_resource_cache: dict = {}


def skill_root() -> Path:
    """当前生效的资源根。"""
    if _resource_root is not None:
        return _resource_root
    env = os.environ.get("TONE_PARTICLES_ROOT")
    return Path(env).expanduser() if env else _DEFAULT_ROOT


def set_resource_root(root=None) -> Path:
    """重设资源根（进程内全局）；传 None 恢复默认。返回生效后的根。"""
    global _resource_root
    _resource_root = Path(root).expanduser().resolve() if root else None
    _resource_cache.clear()
    return skill_root()


def defaults_path() -> Path:
    return skill_root() / "config" / "defaults.json"


def styles_path() -> Path:
    return skill_root() / "config" / "styles.json"


def particles_path() -> Path:
    return skill_root() / "config" / "particles.json"


def __getattr__(name):
    """兼容 `_core.SKILL_ROOT` / `_core.DEFAULTS_PATH` 这类旧写法：按当前资源根动态取值。"""
    if name == "SKILL_ROOT":
        return skill_root()
    accessors = {
        "DEFAULTS_PATH": defaults_path,
        "STYLES_PATH": styles_path,
        "PARTICLES_PATH": particles_path,
    }
    if name in accessors:
        return accessors[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# 颜文字频率预算（次/条）：倾向分四级，见 references/lexicon.md 与 PRD 4.6 第 6 条。
# 高 = 适中档每条 ≤ 1 个；中 = 约每 2 条 1 个；低 = 约每 3–4 条 1 个；极低 = 约每 6 条 1 个。
# 轻档在此基础上再减半。
KAOMOJI_TENDENCY_RATE = {
    "high": 1.0,
    "medium": 0.5,
    "low": 0.25,
    "very_low": 1.0 / 6.0,
}

# 风格文件里的「- **标签**：值」行。标签可能带括号后缀（签名元素（融合时可被借用）、
# 禁忌（重点）），值里也可能再出现冒号（示例：答疑：……），所以分开匹配。
SECTION_RE = re.compile(r"^- \*\*([^*]+)\*\*([^：:]*)[：:]\s*(.*)$", re.MULTILINE)
KAOMOJI_LINE_RE = re.compile(r"^\*\*颜文字\*\*（开启时）[：:]\s*(.+)$", re.MULTILINE)


# --------------------------------------------------------------------------
# 基础读取
# --------------------------------------------------------------------------


def load_json(path: Path, label=None, fallback=None):
    """读取 JSON 文件。

    label 为 None 时用「找不到文件 / 不是合法 JSON」，与既有脚本一致；
    传入「配置文件」等词则替换掉默认措辞。
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if fallback is not None:
            return fallback
        if label:
            raise SystemExit(f"找不到{label}：{path}")
        raise SystemExit(f"找不到文件：{path}")
    except json.JSONDecodeError as exc:
        if label:
            raise SystemExit(f"{label}不是合法 JSON：{path}（{exc}）")
        raise SystemExit(f"不是合法 JSON：{path}（{exc}）")


def _cached_json(path: Path):
    """按 mtime 缓存随包资源（styles / particles）。

    eval 逐条判分会反复读取同一份文件，缓存把 O(回复数 × 解析) 降为 O(1)。
    """
    key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = None
    hit = _resource_cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    data = load_json(path)
    _resource_cache[key] = (mtime, data)
    return data


def load_catalog():
    """返回 (styles.json 全文, {风格 id: 条目})。文件缺失时报错，不静默返回空。"""
    data = _cached_json(styles_path())
    return data, {item["id"]: item for item in data.get("styles", [])}


def load_particles():
    return _cached_json(particles_path())


def catalog_entries(data: dict, index: dict, group=None, include_prompt: bool = False) -> list:
    """统一的风格目录条目形状：CLI --catalog、MCP list_styles、宿主 catalog 共用。"""
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
            entry["prompt"] = style_text(meta)
        items.append(entry)
    return items


def dimension_order(catalog_data: dict) -> list:
    return list(catalog_data.get("dimensions") or [])


def dimension_labels(catalog_data: dict) -> dict:
    return dict(catalog_data.get("dimension_labels") or {})


# --------------------------------------------------------------------------
# 密度区间
# --------------------------------------------------------------------------


def weighted_average(values, weights) -> float:
    total = sum(weights)
    if not total:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / total


def density_range(members, weights, factor: float):
    """多个风格的密度区间：先按权重对上下界分别加权平均，再乘档位系数。"""
    low = weighted_average([item["density"][0] for item in members], weights) * factor
    high = weighted_average([item["density"][1] for item in members], weights) * factor
    return low, high


def style_density_range(meta: dict, factor: float = 1.0):
    """单个风格的密度区间。"""
    low, high = meta.get("density", [0, 0])
    return low * factor, high * factor


def density_factor(level: str) -> float:
    """取档位系数；非法档位给出可读报错而不是裸 KeyError。"""
    if level not in DENSITY_FACTOR:
        raise SystemExit(
            f"density 必须是 {sorted(DENSITY_FACTOR)} 之一，当前为 {level!r}。"
        )
    return DENSITY_FACTOR[level]


def format_range(low: float, high: float) -> str:
    if abs(low - high) < 0.05:
        return f"{low:.1f}"
    return f"{low:.1f}–{high:.1f}"


def conflict_note(main_id: str, accent_id: str, catalog_data: dict) -> bool:
    pairs = {tuple(sorted(pair)) for pair in catalog_data.get("conflict_pairs", [])}
    return tuple(sorted((main_id, accent_id))) in pairs


# --------------------------------------------------------------------------
# 风格文件解析
# --------------------------------------------------------------------------


def style_text(meta: dict) -> str:
    path = skill_root() / meta["file"]
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"找不到风格文件：{path}")


def _clean_label(label: str) -> str:
    """去掉标签尾部的中英文括号后缀，如「禁忌（重点）」→「禁忌」。"""
    return re.sub(r"[（(][^）)]*[）)]\s*$", "", label).strip()


def parse_style_sections(text: str) -> dict:
    """把风格文件里的「- **标签**：值」解析成 {标签: 值}。

    兼容三种写法：
      - **定位**：值
      - **签名元素**（融合时可被借用）：值
      - **禁忌（重点）**：值
    """
    sections = {}
    for match in SECTION_RE.finditer(text):
        label = _clean_label(match.group(1))
        if label:
            sections[label] = match.group(3).strip()
    return sections


def extract_field(text: str, label: str) -> str:
    return parse_style_sections(text).get(label, "")


def extract_signature(text: str) -> str:
    line = extract_field(text, "签名元素")
    line = re.sub(r"^（融合时可被借用）[：:]?", "", line).strip()
    return line


def extract_common_words(lexicon_line: str) -> str:
    match = re.search(r"常用——(.+?)(?:；|$)", lexicon_line)
    if match:
        return match.group(1).strip()
    return lexicon_line


def extract_positioning(text: str) -> str:
    return extract_field(text, "定位").rstrip("。")


def extract_kaomoji_line(text: str) -> str:
    match = KAOMOJI_LINE_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_kaomoji_library(text: str) -> list:
    """解析风格文件末尾的颜文字库，返回 [{"kaomoji": ..., "context": ...}]。

    行格式：**颜文字**（开启时）：(￣▽￣) 认可；( ̄︶ ̄) 从容；…… 倾向：低。
    颜文字本身可能含空格（( ˘ω˘ )），所以按最后一个空格切出情境标签。
    """
    raw = extract_kaomoji_line(text)
    if not raw:
        return []
    raw = re.sub(r"倾向[：:].*$", "", raw).strip().rstrip("。").strip()
    items = []
    for chunk in raw.split("；"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.rsplit(" ", 1)
        if len(parts) == 2 and parts[1]:
            items.append({"kaomoji": parts[0].strip(), "context": parts[1].strip()})
        else:
            items.append({"kaomoji": chunk, "context": ""})
    return items


def kaomoji_budget(tendency: str, level: str = "normal") -> float:
    """每条回复允许的颜文字个数预算（浮点，用于跨回复频率判定）。"""
    base = KAOMOJI_TENDENCY_RATE.get(tendency, 0.5)
    if level == "light":
        base *= 0.5
    return base


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------


def normalize_config(cfg: dict) -> dict:
    """补默认值并做基本校验。"""
    if not isinstance(cfg, dict):
        raise SystemExit("配置必须是 JSON 对象。")

    cfg.setdefault("version", DEFAULT_CONFIG_VERSION)
    cfg.setdefault("mode", "single")
    cfg.setdefault("styles", [])
    cfg.setdefault("density", "standard")
    cfg.setdefault("switch", {})
    if not isinstance(cfg["switch"], dict):
        cfg["switch"] = {}
    cfg["switch"].setdefault("granularity", "per_message")
    cfg["switch"].setdefault("no_repeat_window", 3)
    cfg["switch"].setdefault("locked", False)
    cfg["switch"].setdefault("turns", 3)
    cfg.setdefault("paused", False)
    cfg.setdefault("variants", {})
    kaomoji = cfg.get("kaomoji")
    if not isinstance(kaomoji, dict):
        kaomoji = {}
    kaomoji.setdefault("enabled", False)
    kaomoji.setdefault("level", "light")
    if kaomoji["level"] not in KAOMOJI_LEVELS:
        raise SystemExit(
            f"kaomoji.level 必须是 {sorted(KAOMOJI_LEVELS)} 之一，当前为 {kaomoji['level']!r}。"
        )
    cfg["kaomoji"] = kaomoji
    cfg.setdefault("emoji", "style_default")
    cfg.setdefault("scene_adapt", True)

    if cfg["mode"] not in MODES:
        raise SystemExit(f"mode 必须是 {sorted(MODES)} 之一，当前为 {cfg['mode']!r}。")
    if cfg["density"] not in DENSITY_FACTOR:
        raise SystemExit(
            f"density 必须是 {sorted(DENSITY_FACTOR)} 之一，当前为 {cfg['density']!r}。"
        )
    granularity = cfg["switch"].get("granularity", "per_message")
    if granularity not in GRANULARITIES:
        raise SystemExit(
            f"switch.granularity 必须是 {sorted(GRANULARITIES)} 之一，当前为 {granularity!r}。"
        )
    if not isinstance(cfg["styles"], list) or not cfg["styles"]:
        raise SystemExit("styles 至少要有 1 项。")

    cleaned = []
    seen = set()
    for item in cfg["styles"]:
        if isinstance(item, str):
            item = {"id": item, "weight": 1}
        if not isinstance(item, dict) or "id" not in item:
            raise SystemExit(f"styles 项格式不对：{item!r}")
        sid = str(item["id"]).upper()
        if sid in seen:
            continue
        seen.add(sid)
        weight = item.get("weight", 1)
        try:
            weight = int(weight)
        except (TypeError, ValueError):
            raise SystemExit(f"权重必须是整数：{item!r}")
        if weight <= 0:
            raise SystemExit(f"权重必须为正数：{item!r}")
        cleaned.append({"id": sid, "weight": weight})
    cfg["styles"] = cleaned

    if cfg["mode"] == "single" and len(cleaned) != 1:
        cfg["styles"] = cleaned[:1]

    window = cfg["switch"].get("no_repeat_window", 3)
    try:
        window = int(window)
    except (TypeError, ValueError):
        raise SystemExit("switch.no_repeat_window 必须是整数。")
    cfg["switch"]["no_repeat_window"] = max(0, min(window, 10))

    turns = cfg["switch"].get("turns", 3)
    try:
        turns = int(turns)
    except (TypeError, ValueError):
        raise SystemExit("switch.turns 必须是整数。")
    cfg["switch"]["turns"] = max(1, min(turns, 20))

    return cfg


def migrate_config(cfg: dict) -> dict:
    """按 version 字段迁移旧配置到当前结构。"""
    if not isinstance(cfg, dict):
        raise SystemExit("配置必须是 JSON 对象。")
    version = cfg.get("version", DEFAULT_CONFIG_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise SystemExit(f"配置 version 必须是整数，当前为 {cfg.get('version')!r}。")
    if version > DEFAULT_CONFIG_VERSION:
        raise SystemExit(
            f"配置版本 {version} 高于当前支持的 {DEFAULT_CONFIG_VERSION}，请先升级 skill。"
        )
    cfg["version"] = DEFAULT_CONFIG_VERSION
    return cfg


def load_config(path=None, fallback_defaults: bool = True) -> dict:
    """读取并规范化一份用户配置。

    path 不存在（或未指定）且 fallback_defaults 为真时回退到 defaults.json。
    CLI、MCP 工具与宿主适配层三条入口共用这一份实现。
    """
    path = Path(path) if path else None
    if path is None or not path.exists():
        if fallback_defaults and defaults_path().exists():
            path = defaults_path()
        else:
            raise SystemExit(
                f"找不到配置文件：{path}"
                if path else "没有指定配置，且找不到 config/defaults.json。"
            )
    return normalize_config(migrate_config(load_json(path, label="配置文件")))


def save_config(path, cfg: dict) -> None:
    """原子写回配置。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def save_history(path, history, limit: int = 50) -> None:
    """原子写入风格历史（只留最近 limit 条）。

    历史写不进去不该让整轮对话失败，所以 OSError 只警告不抛出。
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(list(history)[-limit:], ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError as exc:
        print(f"警告：历史文件写入失败（{exc}），本轮未落盘：{path}", file=sys.stderr)


def apply_config_patch(cfg: dict, patch: dict) -> dict:
    """把控制指令 / set_user_style 的配置变更合并进 cfg（不做 normalize）。

    - 只接受 CONFIG_KEYS 里的键，未知键直接报错（防止拼错静默写进配置）
    - 值为 None 表示「不改动」；switch / kaomoji 是字典，做键级合并
    """
    if not isinstance(patch, dict):
        raise SystemExit("配置变更必须是 JSON 对象。")
    for key, value in patch.items():
        if value is None:
            continue
        if key not in CONFIG_KEYS:
            raise SystemExit(
                f"未知配置键：{key}。可用：{', '.join(sorted(CONFIG_KEYS))}"
            )
        if key in ("switch", "kaomoji") and isinstance(value, dict):
            cfg.setdefault(key, {}).update(value)
        else:
            cfg[key] = value
    return cfg


def validate_style_ids(ids, catalog: dict) -> None:
    """校验风格 id 存在，避免非法 id 一路流到下游才炸。"""
    for sid in ids:
        if sid not in catalog:
            raise SystemExit(
                f"未知风格 id：{sid}。可用：{', '.join(sorted(catalog))}"
            )


# --------------------------------------------------------------------------
# 抽样
# --------------------------------------------------------------------------


def weighted_choice(pairs, rng):
    ids = [item[0] for item in pairs]
    weights = [item[1] for item in pairs]
    return rng.choices(ids, weights=weights, k=1)[0]


def banned_set(pool, history, window):
    if window <= 0 or len(pool) <= 1:
        return set()
    # 池子不够大时放宽为「仅避免连续重复」，否则强制轮转会让权重失效
    effective = window if len(pool) > window else 1
    return set(history[-effective:]) if effective > 0 else set()


def pick(cfg: dict, history=None, seed=None) -> dict:
    """按配置抽取本轮风格。history 为最近使用过的风格 id 列表。"""
    history = [str(item).upper() for item in (history or [])]
    rng = random.Random(seed)
    pool = [(item["id"], item["weight"]) for item in cfg["styles"]]
    mode = cfg["mode"]
    notes = []

    if mode == "single":
        return {
            "mode": mode,
            "main": pool[0][0],
            "accents": [],
            "history": history + [pool[0][0]],
            "notes": notes,
        }

    if mode == "blend":
        ranked = sorted(pool, key=lambda item: item[1], reverse=True)
        main = ranked[0][0]
        accents = [item[0] for item in ranked[1:3]]
        total = sum(item[1] for item in ranked)
        if ranked[0][1] / total < 0.5:
            notes.append("主风格权重不足 50%，已按最高权重指定主风格。")
        return {
            "mode": mode,
            "main": main,
            "accents": accents,
            "history": history + [main],
            "notes": notes,
        }

    window = cfg["switch"].get("no_repeat_window", 3)
    if 0 < window and len(pool) <= window:
        notes.append("池不大于去重窗口，已放宽为仅避免连续重复；权重优先。")
    banned = banned_set(pool, history, window)
    candidates = [item for item in pool if item[0] not in banned] or pool
    main = weighted_choice(candidates, rng)

    accents = []
    if mode == "blend_random" and len(pool) > 1 and rng.random() < 0.5:
        rest = [item for item in pool if item[0] != main]
        accents = [weighted_choice(rest, rng)]

    return {
        "mode": mode,
        "main": main,
        "accents": accents,
        "history": history + [main],
        "notes": notes,
    }


def members_with_weights(cfg: dict, ids) -> list:
    """把风格 id 列表配上配置里的权重，返回 [(id, weight), ...]。

    单项时权重恒为 1（单风格没有配比可言）。CLI（--config）与宿主适配层共用，
    保证两处提示词里的主/副配比一致。
    """
    weight_map = {item["id"]: item["weight"] for item in cfg["styles"]}
    members = [(sid, weight_map.get(sid, 1)) for sid in ids]
    if len(members) == 1:
        members = [(members[0][0], 1)]
    return members


def enrich(result: dict, catalog: dict) -> dict:
    """补上风格中文名；未知 id 直接报错，不再静默回退成 id 本身。"""
    main = result["main"]
    validate_style_ids([main] + list(result.get("accents") or []), catalog)
    result["main_name"] = catalog[main]["name"]
    result["accent_names"] = [catalog[sid]["name"] for sid in result.get("accents") or []]
    return result


# --------------------------------------------------------------------------
# 轮次状态机
# --------------------------------------------------------------------------


def advance_turn(state: dict, cfg: dict, topic=None, seed=None) -> dict:
    """按配置的切换粒度决定本轮是否重新抽样。

    state 结构：
        {"history": [...], "current": {"main": ..., "accents": [...]},
         "turn": 3, "topic": "上一轮话题"}

    返回 {"active", "switched", "main", "accents", "notes", "state"}，
    其中 state 是更新后的状态，交给调用方持久化。
    """
    state = dict(state or {})
    history = list(state.get("history") or [])
    current = state.get("current")
    turn = int(state.get("turn") or 0)
    prev_topic = state.get("topic")
    notes = []

    if cfg.get("paused"):
        return {
            "active": False,
            "switched": False,
            "main": current.get("main") if current else None,
            "accents": current.get("accents", []) if current else [],
            "notes": ["语气已暂停，本轮使用中性语气作答。"],
            "state": {**state, "turn": turn + 1},
        }

    switch = cfg.get("switch") or {}
    granularity = switch.get("granularity", "per_message")
    locked = bool(switch.get("locked", False))
    turns = int(switch.get("turns", 3) or 3)

    if current is None:
        switched = True
    elif locked:
        switched = False
        notes.append("switch.locked 为真，沿用当前风格，不重新抽样。")
    elif granularity == "per_message":
        switched = True
    elif granularity == "per_n_turns":
        switched = (turn % turns) == 0
        if not switched:
            notes.append(f"随机粒度为每 {turns} 条切换一次，本轮沿用当前风格。")
    elif granularity == "on_topic_change":
        switched = topic is not None and topic != prev_topic
        if not switched:
            notes.append("话题未变化，本轮沿用当前风格。")
    elif granularity == "per_session":
        switched = False
        notes.append("随机粒度为整个会话只抽一次，本轮沿用会话初始风格。")
    else:
        switched = True

    if switched:
        result = pick(cfg, history, seed=seed)
        main = result["main"]
        accents = result["accents"]
        history = result["history"]
        notes.extend(result.get("notes") or [])
    else:
        main = current["main"]
        accents = list(current.get("accents") or [])

    new_state = {
        "history": history,
        "current": {"main": main, "accents": accents},
        "turn": turn + 1,
        "topic": topic if topic is not None else prev_topic,
    }
    return {
        "active": True,
        "switched": switched,
        "main": main,
        "accents": accents,
        "notes": notes,
        "state": new_state,
    }
