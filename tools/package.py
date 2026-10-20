#!/usr/bin/env python3
"""构建 skill 分发包 `dist/tone-particles-<版本>.zip`。

白名单构建：只把用户装上 skill 就会用到的文件打进 zip——README、SKILL.md、
config/、references/、scripts/、styles/；`eval/`、`integrations/`、`mcp/`、
`Docs/`、`tools/`、`tests/`、`dist/` 都不进包。

zip 顶层是 `tone-particles/` 目录（用户解压即得到 skills/tone-particles/）。
条目排序 + 固定时间戳，同样内容产出字节一致的包，供 GitHub / CNB 两端 Release
使用同一份。

用法：
    python3 tools/package.py          # 按根目录 VERSION 构建并写文件
    python3 tools/package.py --check  # 只校验版本串一致性，不写文件
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
ARCHIVE_PREFIX = "tone-particles"

# (相对路径 glob, 是否必需) —— 就是 README「不随包分发」一节承诺的清单
WHITELIST = [
    ("README.md", True),
    ("SKILL.md", True),
    ("config/defaults.json", True),
    ("config/particles.json", True),
    ("config/styles.json", True),
    ("config/user-config.example.json", True),
    ("references/*.md", True),
    ("scripts/*.py", True),
    ("styles/*.md", True),
]
# 固定时间戳让 zip 可复现（1980-01-01 是 zip 格式的纪元）
FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def read_version() -> str:
    if not VERSION_FILE.exists():
        raise SystemExit(f"找不到版本文件：{VERSION_FILE}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        raise SystemExit("VERSION 文件为空。")
    return version


def check_version_consistency(version: str) -> None:
    """版本号有三处：VERSION（单一来源）、README、mcp/server.py 的 SERVER_VERSION。"""
    problems = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"版本 {version}" not in readme:
        problems.append(f"README.md 未出现「版本 {version}」")
    if f"tone-particles-{version}.zip" not in readme:
        problems.append(f"README.md 未出现 tone-particles-{version}.zip")
    server = (ROOT / "mcp" / "server.py").read_text(encoding="utf-8")
    if f'SERVER_VERSION = "{version}"' not in server:
        problems.append(f"mcp/server.py 的 SERVER_VERSION 不是 {version}")
    if problems:
        raise SystemExit("版本号不一致：\n  - " + "\n  - ".join(problems))


def collect_files() -> list:
    files = []
    for pattern, required in WHITELIST:
        matched = sorted(ROOT.glob(pattern))
        if not matched:
            if required:
                raise SystemExit(f"白名单条目没有匹配到文件：{pattern}")
            continue
        for path in matched:
            if path.is_file():
                files.append(path)
    return sorted(set(files))


def build(version: str) -> tuple:
    files = collect_files()
    target = ROOT / "dist" / f"tone-particles-{version}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(ROOT)
            info = zipfile.ZipInfo(
                f"{ARCHIVE_PREFIX}/{relative.as_posix()}", date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    tmp.replace(target)
    return target, files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 skill 分发包")
    parser.add_argument("--check", action="store_true", help="只校验版本一致性，不写文件")
    args = parser.parse_args(argv)

    version = read_version()
    check_version_consistency(version)
    if args.check:
        print(f"版本一致性 OK：{version}")
        return 0

    target, files = build(version)
    print(f"已构建 {target.relative_to(ROOT)}（{len(files)} 个文件，顶层 {ARCHIVE_PREFIX}/）")
    for path in files:
        print(f"  {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
