#!/usr/bin/env python3
"""版本号同步工具。

版本号在仓库里有几处副本：根目录 VERSION（单一来源）、README 的版本行与
分发包文件名、mcp/server.py 的 SERVER_VERSION、config/styles.json 里每个风格的
version。手工改很容易漏一处，所以这里给一条命令。

用法：
    python3 tools/version.py --check              # 只校验一致性
    python3 tools/version.py --set 0.2.2          # 同步到新版本
    python3 tools/version.py --show               # 打印当前版本

改版本后记得手工在 README 的「版本」一节补一条变更说明——那一节是历史记录，
脚本不代劳。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
README = ROOT / "README.md"
SERVER = ROOT / "mcp" / "server.py"
STYLES = ROOT / "config" / "styles.json"

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def read_version() -> str:
    if not VERSION_FILE.exists():
        raise SystemExit(f"找不到版本文件：{VERSION_FILE}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"版本号格式不对（应为 x.y.z）：{version!r}")
    return version


def _replace_in_file(path: Path, pattern: str, replacement, count: int = 0) -> int:
    text = path.read_text(encoding="utf-8")
    new_text, hits = re.subn(pattern, replacement, text, count=count)
    if hits:
        path.write_text(new_text, encoding="utf-8")
    return hits


def set_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"版本号格式不对（应为 x.y.z）：{version!r}")
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")

    hits = _replace_in_file(README, r"版本 \d+\.\d+\.\d+", f"版本 {version}")
    hits += _replace_in_file(
        README, r"tone-particles-\d+\.\d+\.\d+\.zip", f"tone-particles-{version}.zip")
    print(f"README：更新 {hits} 处")

    hits = _replace_in_file(
        SERVER, r'SERVER_VERSION = "\d+\.\d+\.\d+"', f'SERVER_VERSION = "{version}"')
    print(f"mcp/server.py：更新 {hits} 处")

    data = json.loads(STYLES.read_text(encoding="utf-8"))
    for style in data.get("styles", []):
        if not isinstance(style.get("version"), str):
            raise SystemExit(f"风格 {style.get('id')} 的 version 字段不是字符串。")
    # 按原文替换，不做 JSON 重排——styles.json 是手工排版的紧凑格式，
    # 整体重新序列化会产生几百行无意义的 diff。
    hits = _replace_in_file(
        STYLES, r'("version":\s*")\d+\.\d+\.\d+(")', rf'\g<1>{version}\g<2>')
    print(f"config/styles.json：更新 {hits} 处")

    print(f"版本已同步到 {version}")
    print("提醒：README 的「版本」一节要手工补一条变更说明。")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="版本号同步与校验")
    parser.add_argument("--set", dest="target", help="同步到指定版本，例如 0.2.2")
    parser.add_argument("--check", action="store_true", help="只校验一致性")
    parser.add_argument("--show", action="store_true", help="打印当前版本")
    args = parser.parse_args(argv)

    if args.target:
        set_version(args.target)
        return 0

    version = read_version()
    if args.show:
        print(version)
        return 0

    sys.path.insert(0, str(ROOT / "tools"))
    import package

    try:
        package.check_version_consistency(version)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"版本一致性 OK：{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
