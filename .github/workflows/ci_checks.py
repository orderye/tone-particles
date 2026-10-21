#!/usr/bin/env python3
"""CI 专用的补充检查（纯标准库）。

放在 .github/workflows/ 下是因为它只服务流水线：仓库其它位置不放 CI 专用脚本。
GitHub Actions 与 CNB 两端都调用这一份，保证两端跑的检查内容一致。

子命令：
    config   配置与 schema 校验：四个 config JSON、风格目录、用户配置示例、
             MCP 工具入参 schema
    smoke    CLI 冒烟：三个脚本的真实调用、输出非空、JSON 可解析
    report   读 eval/report.json，汇总「通过 / 未达标 / 未评测」并决定退出码

退出码：全部通过 0，任一失败 1。report 子命令里「未评测」不阻断（离线 CI 没有
评审后端），但会逐条打印出来，不假装全部达标。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _core  # noqa: E402

RESULTS: list = []


def record(name: str, ok, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def run(name: str, args: list, stdin: str | None = None, expect_json: bool = False) -> str:
    """跑一条命令，记录退出码 / 输出是否非空 / JSON 是否可解析。"""
    proc = subprocess.run(
        [sys.executable, *args], cwd=ROOT, input=stdin,
        capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        record(name, False, f"退出码 {proc.returncode}：{(proc.stderr or proc.stdout)[-300:]}")
        return ""
    if not proc.stdout.strip():
        record(name, False, "输出为空")
        return proc.stdout
    if expect_json:
        try:
            json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            record(name, False, f"输出不是合法 JSON：{exc}")
            return proc.stdout
    record(name, True)
    return proc.stdout


# --------------------------------------------------------------------------
# config：配置与 schema 校验
# --------------------------------------------------------------------------


def check_config_files() -> None:
    for name in ["defaults.json", "particles.json", "styles.json", "user-config.example.json"]:
        path = ROOT / "config" / name
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            record(f"config/{name} 可解析", False, str(exc))
        else:
            record(f"config/{name} 可解析", True)


def check_styles_json() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    data = json.loads((ROOT / "config" / "styles.json").read_text(encoding="utf-8"))
    styles = data.get("styles", [])
    record("styles.json 声明 21 个风格", len(styles) == 21, f"实际 {len(styles)}")

    bad_fields = []
    bad_version = []
    missing_file = []
    for style in styles:
        for field in ["id", "name", "file", "version"]:
            if not style.get(field):
                bad_fields.append(f"{style.get('id', '?')} 缺 {field}")
        if style.get("version") != version:
            bad_version.append(f"{style.get('id')}={style.get('version')}")
        if not (ROOT / style.get("file", "")).exists():
            missing_file.append(style.get("file", "?"))
    record("styles.json 每个风格字段齐全", not bad_fields, "；".join(bad_fields[:5]))
    record(
        f"styles.json 各风格 version 与 VERSION（{version}）一致",
        not bad_version, "；".join(bad_version[:5]))
    record("styles.json 指向的风格文件都存在", not missing_file, "；".join(missing_file[:5]))


def check_user_configs() -> None:
    """用户配置示例与默认配置要能通过核心的 schema 校验（严格模式）。"""
    _, index = _core.load_catalog()
    for name in ["defaults.json", "user-config.example.json"]:
        path = ROOT / "config" / name
        cfg = json.loads(path.read_text(encoding="utf-8"))
        result = _core.validate_config(cfg, index, strict=True)
        record(
            f"config/{name} 通过配置 schema 校验（严格模式）",
            not result["errors"],
            "；".join(result["errors"][:5]))


def check_mcp_schemas() -> None:
    sys.path.insert(0, str(ROOT / "mcp"))
    try:
        import schemas  # noqa: E402
    except ImportError as exc:
        record("MCP 工具入参 schema 可加载", False, str(exc))
        return
    expected = {"list_styles", "get_style_prompt", "set_user_style", "pick_next_style"}
    record("MCP schema 覆盖四个工具", set(schemas.SCHEMAS) == expected, str(sorted(schemas.SCHEMAS)))
    bad = []
    for name, schema in schemas.SCHEMAS.items():
        if schema.get("type") != "object":
            bad.append(f"{name} 的 type 不是 object")
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties:
            bad.append(f"{name} 缺 properties")
            continue
        for field in schema.get("required", []):
            if field not in properties:
                bad.append(f"{name} 的 required 字段 {field} 未在 properties 里声明")
    record("MCP 每个工具的 schema 字段齐全", not bad, "；".join(bad[:5]))


def command_config() -> int:
    check_config_files()
    check_styles_json()
    check_user_configs()
    check_mcp_schemas()
    return report()


# --------------------------------------------------------------------------
# smoke：CLI 冒烟
# --------------------------------------------------------------------------


def command_smoke() -> int:
    run("CLI：pick_style --catalog", ["scripts/pick_style.py", "--catalog"])
    run(
        "CLI：pick_style --simulate（带示例配置）",
        ["scripts/pick_style.py", "config/user-config.example.json", "[]",
         "--simulate", "1000", "--seed", "42"],
        expect_json=True)
    run(
        "CLI：compose_prompt --main S04",
        ["scripts/compose_prompt.py", "--main", "S04"])
    run(
        "CLI：compose_prompt --main S09 --accent S04 --json",
        ["scripts/compose_prompt.py", "--main", "S09", "--accent", "S04", "--json"],
        expect_json=True)
    run(
        "CLI：compose_prompt --config config/user-config.example.json --json",
        ["scripts/compose_prompt.py", "--config", "config/user-config.example.json", "--json"],
        expect_json=True)
    run(
        "CLI：check_density --style S09（stdin）",
        ["scripts/check_density.py", "--style", "S09"],
        stdin="哼，这种小问题还要我看吗……算了。第 8 行少了个括号，改完就能跑了。\n")
    run("CLI：check_density --help", ["scripts/check_density.py", "--help"])
    return report()


# --------------------------------------------------------------------------
# report：评测报告汇总
# --------------------------------------------------------------------------


def metric_status(item: dict) -> str:
    """指标状态：优先用新格式的 status 字段，回落到旧的 passed / skipped。

    评测报告的指标结构在演进（status: passed/failed/not_evaluated/blocked），
    旧字段 passed / skipped 仍被保留；两种都认，CI 才不会随格式变动误判。
    """
    status = item.get("status")
    if status:
        return str(status)
    if item.get("skipped"):
        return "not_evaluated"
    passed = item.get("passed")
    if passed is None:
        return "not_evaluated"
    return "passed" if passed else "failed"


def command_report(path: str) -> int:
    report_path = Path(path)
    if not report_path.exists():
        record(f"评测报告存在（{path}）", False, "文件不存在")
        return report()
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        record(f"评测报告可解析（{path}）", False, str(exc))
        return report()

    metrics = payload.get("metrics", [])
    statuses = {item.get("metric", "?"): metric_status(item) for item in metrics}
    passed = [item for item in metrics if metric_status(item) == "passed"]
    failed = [item for item in metrics if metric_status(item) == "failed"]
    not_evaluated = [item for item in metrics if metric_status(item) == "not_evaluated"]
    blocked = [item for item in metrics if metric_status(item) == "blocked"]

    record(
        f"评测报告含指标（{len(metrics)} 项）",
        bool(metrics), "报告里没有任何指标")
    record(
        f"已评测指标全部达标（{len(passed)}/{len(passed) + len(failed)}）",
        not failed,
        "；".join(f"{item.get('metric')}：{item.get('value')}" for item in failed[:5]))
    record(
        "没有因系统错误被阻塞的指标",
        not blocked,
        "；".join(f"{item.get('metric')}：{item.get('value')}" for item in blocked[:5]))

    labels = {
        "passed": "通过", "failed": "未达标",
        "not_evaluated": "未评测", "blocked": "被阻塞",
    }
    print("评测指标状态：")
    for item in metrics:
        status = metric_status(item)
        print(f"  [{labels.get(status, status)}] {item.get('metric')}："
              f"{item.get('value')}（门槛 {item.get('threshold')}）")
    verdict = payload.get("verdict")
    if isinstance(verdict, dict) and verdict:
        print(f"评测判定：退出码 {verdict.get('exit_code')}，"
              f"未达标 {len(verdict.get('failed', []))} 项，"
              f"被阻塞 {len(verdict.get('blocked', []))} 项，"
              f"未评测 {len(verdict.get('not_evaluated', []))} 项")
    print(
        f"\n共 {len(metrics)} 项指标：{len(passed)} 项达标，"
        f"{len(failed)} 项未达标，{len(not_evaluated)} 项未评测，{len(blocked)} 项被阻塞。")
    if not_evaluated:
        print("未评测项（离线 CI 没有评审后端，不阻断，但如实列出）：")
        for item in not_evaluated:
            print(f"  - {item.get('metric')}：{item.get('value')}"
                  f"（门槛 {item.get('threshold')}）")
    if blocked:
        print("被阻塞项（没能得出结论，视为未通过）：")
        for item in blocked:
            print(f"  - {item.get('metric')}：{item.get('value')}")
    return report()


# --------------------------------------------------------------------------


def report() -> int:
    failed = [(name, detail) for name, ok, detail in RESULTS if not ok]
    for name, ok, detail in RESULTS:
        suffix = f"：{detail}" if detail and not ok else ""
        print(f"  {'✓' if ok else '✗'} {name}{suffix}")
    print(f"\n检查：通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项。")
    return 1 if failed else 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    command = argv[0]
    if command == "config":
        return command_config()
    if command == "smoke":
        return command_smoke()
    if command == "report":
        return command_report(argv[1] if len(argv) > 1 else "eval/report.json")
    print(f"未知子命令：{command}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
