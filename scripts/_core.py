#!/usr/bin/env python3
"""tone-particles 共享核心。

三个 CLI、宿主适配层与工具接口服务共用这一份实现：配置读写、风格目录、密度区间、
风格文件解析、抽样与轮次状态机都只在这里定义一次，避免同一套语义在多处漂移。

纯标准库，无第三方依赖。
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import re
import sys
import tempfile
import time
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

# 配置里允许出现的顶层键。version 是配置自身的版本号，其余是可改写项。
TOP_LEVEL_KEYS = CONFIG_KEYS | {"version"}
# switch / kaomoji 的合法子键
SWITCH_KEYS = {"granularity", "no_repeat_window", "locked", "turns"}
KAOMOJI_KEYS = {"enabled", "level"}
# emoji 目前只有一个取值。它在 README 的字段表里没有单列，非法值只告警不拒绝。
EMOJI_VALUES = {"style_default"}
# 老师风格的子模式
VARIANT_VALUES = {"gentle", "strict"}
# 目前只有老师风格支持子模式
VARIANT_STYLES = {"S20"}
# 用户配置的权限：只允许本人读写。
CONFIG_FILE_MODE = 0o600
# 跨进程锁的默认等待上限（秒）
LOCK_TIMEOUT = 5.0


def _copy_config(cfg: dict) -> dict:
    """拷贝配置及其嵌套字典，避免归一化时改动调用方持有的对象。"""
    out = dict(cfg)
    for key in ("switch", "kaomoji", "variants"):
        value = out.get(key)
        if isinstance(value, dict):
            out[key] = dict(value)
    styles = out.get("styles")
    if isinstance(styles, list):
        out["styles"] = [dict(item) if isinstance(item, dict) else item for item in styles]
    return out


def normalize_config(cfg: dict, *, warnings: list | None = None) -> dict:
    """补默认值并做基本校验。

    返回**新的**配置对象，不改动传入的字典。越界但可以修正的数值（去重窗口、
    轮数）会被夹到合法区间，并在 warnings 里留痕——静默夹取会让用户误以为自己
    设的值生效了。真正非法的值（枚举错、权重非正）直接报错，不写进配置。
    """
    if not isinstance(cfg, dict):
        raise SystemExit("配置必须是 JSON 对象。")

    cfg = _copy_config(cfg)
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
        if isinstance(weight, bool):
            raise SystemExit(f"权重必须是整数：{item!r}")
        try:
            weight = int(weight)
        except (TypeError, ValueError):
            raise SystemExit(f"权重必须是整数：{item!r}")
        if weight <= 0:
            raise SystemExit(f"权重必须为正数：{item!r}")
        cleaned.append({"id": sid, "weight": weight})
    cfg["styles"] = cleaned

    if cfg["mode"] == "single" and len(cleaned) != 1:
        if warnings is not None:
            warnings.append(
                f"single 模式只使用 1 个风格，配置里的 {len(cleaned)} 个已按第一个截断。")
        cfg["styles"] = cleaned[:1]

    window = cfg["switch"].get("no_repeat_window", 3)
    try:
        window = int(window)
    except (TypeError, ValueError):
        raise SystemExit("switch.no_repeat_window 必须是整数。")
    if not 0 <= window <= 10:
        clamped = max(0, min(window, 10))
        if warnings is not None:
            warnings.append(
                f"switch.no_repeat_window 必须是 0–10，当前为 {window}，已夹到 {clamped}。")
        window = clamped
    cfg["switch"]["no_repeat_window"] = window

    turns = cfg["switch"].get("turns", 3)
    try:
        turns = int(turns)
    except (TypeError, ValueError):
        raise SystemExit("switch.turns 必须是整数。")
    if not 1 <= turns <= 20:
        clamped = max(1, min(turns, 20))
        if warnings is not None:
            warnings.append(
                f"switch.turns 必须是 1–20，当前为 {turns}，已夹到 {clamped}。")
        turns = clamped
    cfg["switch"]["turns"] = turns

    return cfg


def migrate_config(cfg: dict) -> dict:
    """按 version 字段迁移旧配置到当前结构。返回新对象，不改动传入的字典。"""
    if not isinstance(cfg, dict):
        raise SystemExit("配置必须是 JSON 对象。")
    cfg = _copy_config(cfg)
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


def validate_config(cfg: dict, catalog: dict | None = None, *, strict: bool = False) -> dict:
    """检查归一化之后的配置，返回 {"errors": [...], "warnings": [...]}。

    策略：
    - 非法值（枚举错、权重非正、风格 id 不存在）→ errors，必须拒绝写入。
    - 未知字段 → warnings，默认保留并告警；strict 模式下升级为 errors。
    - 越界数值已在 normalize 里夹取，这里只作为 warning 再报一次。
    """
    errors: list = []
    warnings: list = []

    for key in cfg:
        if key not in TOP_LEVEL_KEYS:
            message = f"未知配置字段 {key!r}，已保留但不会生效。"
            (errors if strict else warnings).append(message)

    for key, allowed in (("switch", SWITCH_KEYS), ("kaomoji", KAOMOJI_KEYS)):
        section = cfg.get(key)
        if isinstance(section, dict):
            for sub in section:
                if sub not in allowed:
                    message = f"未知配置字段 {key}.{sub}，已保留但不会生效。"
                    (errors if strict else warnings).append(message)

    if cfg.get("emoji") not in EMOJI_VALUES:
        warnings.append(
            f"emoji 的取值 {cfg.get('emoji')!r} 不在 {sorted(EMOJI_VALUES)} 内，"
            "当前按原样保留但不参与任何逻辑。")

    variants = cfg.get("variants")
    if isinstance(variants, dict):
        for sid, value in variants.items():
            sid = str(sid).upper()
            if value not in VARIANT_VALUES:
                errors.append(
                    f"variants.{sid} 必须是 {sorted(VARIANT_VALUES)} 之一，"
                    f"当前为 {value!r}。")
            elif sid not in VARIANT_STYLES:
                warnings.append(
                    f"variants.{sid} 目前没有支持的子模式（只有 "
                    f"{'、'.join(sorted(VARIANT_STYLES))} 支持），该值不会生效。")

    if catalog is not None:
        for item in cfg.get("styles") or []:
            sid = item.get("id") if isinstance(item, dict) else item
            if str(sid).upper() not in catalog:
                errors.append(f"未知风格 id：{sid}。可用：{', '.join(sorted(catalog))}")

    return {"errors": errors, "warnings": warnings}


def load_config(path=None, fallback_defaults: bool = True, *,
                strict: bool = False, quiet: bool = False) -> dict:
    """读取并规范化一份用户配置。

    path 不存在（或未指定）且 fallback_defaults 为真时回退到 defaults.json。
    CLI、MCP 工具与宿主适配层三条入口共用这一份实现。

    strict 为真时，未知字段也会让加载失败（默认只告警并保留）。
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
    warnings: list = []
    cfg = normalize_config(
        migrate_config(load_json(path, label="配置文件")), warnings=warnings)
    catalog = load_catalog()[1] if styles_path().exists() else None
    report = validate_config(cfg, catalog, strict=strict)
    if report["errors"]:
        raise SystemExit("配置校验未通过：\n  - " + "\n  - ".join(report["errors"]))
    for message in warnings + report["warnings"]:
        if strict:
            raise SystemExit(f"配置校验未通过：{message}")
        if not quiet:
            print(f"警告：{message}", file=sys.stderr)
    return cfg


# --------------------------------------------------------------------------
# 原子写入与跨进程锁
# --------------------------------------------------------------------------


def _fsync_dir(directory: Path) -> None:
    """把目录项落盘（POSIX）。失败不影响正确性，忽略即可。"""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path, text: str, *, mode: int | None = None) -> None:
    """同目录临时文件 → flush/fsync → 原子替换。

    临时文件名带随机后缀：多个进程同时写同一份文件时不会共用同一个中间文件
    （共用的话会出现「一个进程替换掉另一个进程正在写的文件」，落盘结果是半截 JSON）。
    出错时旧文件保持原样，临时文件被清理。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def _lock_file(handle) -> None:
    """对文件句柄加独占锁（非阻塞）。POSIX 用 flock，Windows 用 msvcrt。"""
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def config_lock(path, timeout: float = LOCK_TIMEOUT):
    """跨进程互斥锁。

    锁文件独立于配置本身：配置用原子替换写入，锁在被替换掉的旧 inode 上会失效。
    线程锁不够用——多个宿主进程同时写同一份用户配置是真实场景。

    拿不到锁就报错，不静默降级成「没有保护地写」。
    """
    path = Path(path)
    lock_path = path.parent / (path.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
    except OSError as exc:
        raise SystemExit(f"打不开配置锁文件：{lock_path}（{exc}）")
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        if os.name == "nt":
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
        while True:
            try:
                _lock_file(handle)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SystemExit(
                        f"等待配置锁超时（{timeout:g}s）：{lock_path}。"
                        "另一个进程正在写同一份配置，请稍后重试。")
                time.sleep(0.02)
        yield
    finally:
        if acquired:
            try:
                _unlock_file(handle)
            except OSError:
                pass
        handle.close()


def save_config(path, cfg: dict, *, verify: bool = True) -> None:
    """原子写回配置。

    写入前先归一化并校验：非法配置不会落盘，旧配置保持原样。写入后重新读取
    并归一化，确认落盘内容仍可读——「写完不校验」等于把失败藏起来。
    """
    path = Path(path)
    payload = normalize_config(migrate_config(cfg))
    atomic_write_text(
        path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        mode=CONFIG_FILE_MODE)
    if not verify:
        return
    try:
        written = load_config(path, fallback_defaults=False, quiet=True)
    except SystemExit as exc:
        raise SystemExit(f"配置写入后校验失败：{exc}")
    if written != payload:
        raise SystemExit("配置写入后校验失败：落盘内容与预期不一致。")


def save_history(path, history, limit: int = 50) -> None:
    """原子写入风格历史（只留最近 limit 条）。

    历史写不进去不该让整轮对话失败，所以 OSError 只警告不抛出。
    """
    path = Path(path)
    try:
        atomic_write_text(
            path, json.dumps(list(history)[-limit:], ensure_ascii=False))
    except OSError as exc:
        print(f"警告：历史文件写入失败（{exc}），本轮未落盘：{path}", file=sys.stderr)


def apply_config_patch(cfg: dict, patch: dict) -> dict:
    """把控制指令 / set_user_style 的配置变更合并进 cfg（不做 normalize）。

    - 只接受 CONFIG_KEYS 里的键，未知键直接报错（防止拼错静默写进配置）
    - 值为 None 表示「不改动」；switch / kaomoji 是字典，做键级合并
    - 返回新对象，不改动传入的 cfg
    """
    if not isinstance(patch, dict):
        raise SystemExit("配置变更必须是 JSON 对象。")
    cfg = _copy_config(cfg)
    for key, value in patch.items():
        if value is None:
            continue
        if key not in CONFIG_KEYS:
            raise SystemExit(
                f"未知配置键：{key}。可用：{', '.join(sorted(CONFIG_KEYS))}"
            )
        if key in ("switch", "kaomoji") and isinstance(value, dict):
            current = cfg.get(key)
            merged = dict(current) if isinstance(current, dict) else {}
            merged.update(value)
            cfg[key] = merged
        else:
            cfg[key] = value
    return cfg


def update_config_file(path, patch: dict, *, fallback_defaults: bool = True,
                       strict: bool = False, timeout: float = LOCK_TIMEOUT) -> dict:
    """加锁的「读—改—写」，配置更新的唯一入口。

    锁内重新读取当前配置再合并补丁：并发更新时不会用一份旧读覆盖掉别人刚写入
    的、不相关的字段。写完重新校验，失败时旧配置原样保留。
    """
    path = Path(path)
    with config_lock(path, timeout=timeout):
        cfg = load_config(path, fallback_defaults=fallback_defaults, strict=strict)
        merged = apply_config_patch(cfg, patch)
        merged = normalize_config(migrate_config(merged))
        save_config(path, merged, verify=True)
        return merged


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
