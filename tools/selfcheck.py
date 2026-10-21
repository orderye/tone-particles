#!/usr/bin/env python3
"""仓库自检：本地与两份 CI（GitHub Actions / CNB）共用这一份清单。

检查内容：
1. 四个 config JSON 可解析
2. 21 个风格文件存在且含必需字段
3. styles/*.md 与 config/styles.json 的密度区间 / 颜文字倾向 / 签名元素一致
4. 每个风格的颜文字库都能被 check_density 检出（防静默漏检）
5. CLI 冒烟：pick_style / compose_prompt / check_density
6. 单元测试：tests/ 下的三个测试文件

用法：python3 tools/selfcheck.py
退出码：全部通过 0，任一失败 1。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _core  # noqa: E402
import check_density  # noqa: E402

REQUIRED_CONFIGS = ["defaults.json", "particles.json", "styles.json", "user-config.example.json"]
STYLE_FIELDS = ["定位", "词库", "签名元素", "颜文字"]
TENDENCY_MAP = {"极低": "very_low", "高": "high", "中": "medium", "低": "low"}
TEST_FILES = [
    "tests/test_core.py",
    "tests/test_host.py",
    "tests/test_mcp.py",
    "tests/test_config.py",
    "tests/test_protocol.py",
    "tests/test_safety.py",
    "tests/test_eval.py",
]

RESULTS: list = []


def record(name: str, ok, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


# --------------------------------------------------------------------------
# 各项检查
# --------------------------------------------------------------------------


def check_configs() -> None:
    for name in REQUIRED_CONFIGS:
        path = ROOT / "config" / name
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            record(f"config/{name} 可解析", False, str(exc))
        else:
            record(f"config/{name} 可解析", True)


def check_styles() -> None:
    data, index = _core.load_catalog()
    record("styles.json 声明 21 个风格", len(index) == 21, f"实际 {len(index)}")
    bad = []
    for meta in index.values():
        path = ROOT / meta["file"]
        if not path.exists():
            bad.append(f"{meta['id']} 缺文件 {meta['file']}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [field for field in STYLE_FIELDS if field not in text]
        if missing:
            bad.append(f"{meta['id']} 缺字段 {'、'.join(missing)}")
    record("21 个风格文件含必需字段", not bad, "；".join(bad[:5]))


def parse_md_density(section: str):
    """从「密度与符号」段解析出 [low, high]；解析不出来返回 None。"""
    match = re.search(r"[≤<]\s*(\d+(?:\.\d+)?)\s*次/百字", section)
    if match:
        return [0.0, float(match.group(1))]
    match = re.search(r"(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*次/百字", section)
    if match:
        return [float(match.group(1)), float(match.group(2))]
    match = re.search(r"(\d+(?:\.\d+)?)\s*次/百字", section)
    if match:
        return [float(match.group(1)), float(match.group(1))]
    return None


def check_md_json_consistency() -> None:
    """styles/*.md 是给人/模型看的，styles.json 是运行时权威——两处必须一致。

    密度、颜文字倾向、签名元素三组字段在两边各存一份（md 供阅读、json 供计算），
    漂移不会报错、只会静默改变行为，所以在这里兜住。
    """
    _, index = _core.load_catalog()
    density_bad, tendency_bad, signature_bad = [], [], []
    for meta in index.values():
        text = _core.style_text(meta)
        sections = _core.parse_style_sections(text)

        md_density = parse_md_density(sections.get("密度与符号", ""))
        json_density = [float(value) for value in meta.get("density", [])]
        if md_density is None or len(json_density) != 2 or md_density != json_density:
            density_bad.append(
                f"{meta['id']}：md={md_density} json={json_density}")

        kao_line = _core.extract_kaomoji_line(text)
        tendency = re.search(r"倾向[：:]\s*(极低|高|中|低)", kao_line)
        md_tendency = TENDENCY_MAP.get(tendency.group(1)) if tendency else None
        if md_tendency != meta.get("kaomoji"):
            tendency_bad.append(
                f"{meta['id']}：md={md_tendency} json={meta.get('kaomoji')}")

        md_signature = sections.get("签名元素", "").strip().rstrip("。").strip()
        json_signature = "；".join(meta.get("signature", []))
        if md_signature != json_signature:
            signature_bad.append(f"{meta['id']}：md 与 json 不一致")

    record("密度区间 md 与 json 一致", not density_bad, "；".join(density_bad[:3]))
    record("颜文字倾向 md 与 json 一致", not tendency_bad, "；".join(tendency_bad[:3]))
    record("签名元素 md 与 json 一致", not signature_bad, "；".join(signature_bad[:3]))


def check_kaomoji_detection() -> None:
    """风格库里的每个颜文字都必须能被 check_density 检出。

    检出依赖 KAOMOJI_CHARS 白名单阈值，新字符不在白名单时检测会静默失效——
    这里把静默失效变成响亮失败。
    """
    _, index = _core.load_catalog()
    bad = []
    for meta in index.values():
        for item in _core.extract_kaomoji_library(_core.style_text(meta)):
            if not check_density.find_kaomoji(item["kaomoji"]):
                bad.append(f"{meta['id']} {item['kaomoji']}")
    record("风格库颜文字全部可检出", not bad, "；".join(bad[:5]))


def run_command(name: str, args: list, stdin: str | None = None) -> None:
    proc = subprocess.run(
        [sys.executable, *args], cwd=ROOT, input=stdin,
        capture_output=True, text=True)
    detail = "" if proc.returncode == 0 else (proc.stderr or proc.stdout)[-300:]
    record(name, proc.returncode == 0, detail)


def check_cli() -> None:
    run_command(
        "CLI：pick_style --simulate",
        ["scripts/pick_style.py", "config/user-config.example.json", "[]",
         "--simulate", "1000", "--seed", "42"])
    run_command("CLI：pick_style --catalog", ["scripts/pick_style.py", "--catalog"])
    run_command(
        "CLI：compose_prompt --main/--accent",
        ["scripts/compose_prompt.py", "--main", "S09", "--accent", "S04", "--json"])
    run_command(
        "CLI：compose_prompt --config",
        ["scripts/compose_prompt.py", "--config", "config/user-config.example.json", "--json"])
    run_command(
        "CLI：check_density（stdin）",
        ["scripts/check_density.py", "--style", "S09"],
        stdin="哼，这种小问题还要我看吗……算了。第 8 行少了个括号，改完就能跑了。\n")


def check_tests() -> None:
    for path in TEST_FILES:
        run_command(f"单元测试：{path}", [path])


def check_eval() -> None:
    """评测体系的两个入口：用例结构校验与离线确定性评测。"""
    run_command("评测：用例结构校验", ["eval/validate_cases.py"])
    run_command("评测：确定性指标（离线）", ["eval/run.py", "--json"])


def check_version() -> None:
    """版本号一致性：VERSION（单一来源）、README、MCP 服务、styles.json。"""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import package
    except ImportError as exc:
        record("版本号一致（VERSION / README / MCP / styles.json）", False, str(exc))
        return
    try:
        version = package.read_version()
        package.check_version_consistency(version)
    except SystemExit as exc:
        record("版本号一致（VERSION / README / MCP / styles.json）", False, str(exc))
    else:
        record("版本号一致（VERSION / README / MCP / styles.json）", True)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def main() -> int:
    check_configs()
    check_styles()
    check_md_json_consistency()
    check_kaomoji_detection()
    check_version()
    check_cli()
    check_eval()
    check_tests()

    failed = [(name, detail) for name, ok, detail in RESULTS if not ok]
    for name, ok, detail in RESULTS:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"\n自检：通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项。")
    for name, detail in failed:
        print(f"  ✗ {name}：{detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
