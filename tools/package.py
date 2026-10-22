#!/usr/bin/env python3
"""构建并校验 skill 分发包 `dist/tone-particles-<版本>.zip`。

白名单构建：只把用户装上 skill 就会用到的文件打进 zip——README、SKILL.md、
config/、references/、scripts/、styles/；`eval/`、`integrations/`、`mcp/`、
`Docs/`、`tools/`、`tests/`、`dist/` 都不进包。

zip 顶层是 `tone-particles/` 目录（用户解压即得到 skills/tone-particles/）。
条目排序 + 固定时间戳，同样内容产出字节一致的包，供 GitHub / CNB 两端 Release
使用同一份。

用法：
    python3 tools/package.py            # 按根目录 VERSION 构建并写文件
    python3 tools/package.py --check    # 只校验版本串一致性，不写文件
    python3 tools/package.py --verify   # 供应链校验：可复现性 / 内容清单 /
                                        # 路径安全 / 解压最小安装 / SHA-256 清单
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import tempfile
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
    ("assets/*.svg", False),
]
# 固定时间戳让 zip 可复现（1980-01-01 是 zip 格式的纪元）
FIXED_DATE = (1980, 1, 1, 0, 0, 0)

# 运行时必需文件：少一个包就装不起来（相对包根）
REQUIRED_FILES = [
    "README.md",
    "SKILL.md",
    "config/defaults.json",
    "config/particles.json",
    "config/styles.json",
    "config/user-config.example.json",
    "scripts/_core.py",
    "scripts/_context.py",
    "scripts/check_density.py",
    "scripts/compose_prompt.py",
    "scripts/pick_style.py",
]
# 不得进包的文件名（相对包根，或文件名本身）
FORBIDDEN_NAMES = [
    "config/user-config.json",
    "config/tone-history.json",
    ".DS_Store",
]
# 不得进包的目录名（出现在任意路径段都算违规）
FORBIDDEN_DIRS = [
    "eval", "tests", "tools", "integrations", "mcp", "dist",
    "Docs", "docs", ".git", ".github", ".cnb-worktree", "__pycache__",
]
# 不得进包的文件后缀
FORBIDDEN_SUFFIXES = [".lock", ".pyc", ".pyo", ".log", ".tmp", ".bak", ".orig"]
# 机器特定路径（打包时若出现，说明把本机路径写进了分发内容）
MACHINE_PATH_PATTERNS = ["/Users/", "/home/", "C:\\Users\\"]
# 密钥形态（宁可误报也不要把凭证打进分发包）
SECRET_PATTERNS = [
    r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY",
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
]


def read_version() -> str:
    if not VERSION_FILE.exists():
        raise SystemExit(f"找不到版本文件：{VERSION_FILE}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        raise SystemExit("VERSION 文件为空。")
    return version


def check_version_consistency(version: str) -> None:
    """版本号有四处：VERSION（单一来源）、README、mcp/server.py 的 SERVER_VERSION、config/styles.json 各风格的 version。"""
    problems = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"版本 {version}" not in readme:
        problems.append(f"README.md 未出现「版本 {version}」")
    if f"tone-particles-{version}.zip" not in readme:
        problems.append(f"README.md 未出现 tone-particles-{version}.zip")
    server = (ROOT / "mcp" / "server.py").read_text(encoding="utf-8")
    if f'SERVER_VERSION = "{version}"' not in server:
        problems.append(f"mcp/server.py 的 SERVER_VERSION 不是 {version}")
    styles = json.loads((ROOT / "config" / "styles.json").read_text(encoding="utf-8"))
    bad = [s["id"] for s in styles.get("styles", []) if s.get("version") != version]
    if bad:
        problems.append(
            f"config/styles.json 中 {len(bad)} 个风格的 version 不是 {version}：{', '.join(bad)}")
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


def build_to(version: str, target: Path) -> tuple:
    """把白名单内容打成 zip 写到 target。条目排序 + 固定时间戳 + 固定权限位。"""
    files = collect_files()
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


def build(version: str) -> tuple:
    return build_to(version, ROOT / "dist" / f"tone-particles-{version}.zip")


# --------------------------------------------------------------------------
# 供应链校验
# --------------------------------------------------------------------------


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Checks:
    """收集检查项，最后统一打印并决定退出码。"""

    def __init__(self) -> None:
        self.items: list = []

    def add(self, name: str, ok, detail: str = "") -> None:
        self.items.append((name, bool(ok), detail))

    @property
    def failures(self) -> list:
        return [(name, detail) for name, ok, detail in self.items if not ok]

    def finish(self) -> int:
        for name, ok, detail in self.items:
            suffix = f"：{detail}" if detail and not ok else ""
            print(f"  {'✓' if ok else '✗'} {name}{suffix}")
        failed = self.failures
        print(f"\n供应链校验：通过 {len(self.items) - len(failed)} 项，失败 {len(failed)} 项。")
        return 1 if failed else 0


def unsafe_reason(name: str) -> str:
    """返回条目名不安全的理由；安全则返回空串。"""
    if not name:
        return "空条目名"
    if "\x00" in name:
        return "含 NUL 字节"
    if any(ord(ch) < 32 for ch in name):
        return "含控制字符"
    if "\\" in name:
        return "含反斜杠（Windows 路径分隔符）"
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return "绝对路径"
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "含空段、. 或 .. 路径段"
    if any(part != part.strip() for part in parts):
        return "路径段首尾有空白"
    return ""


def inspect_archive(archive_path: Path, checks: Checks) -> list:
    """检查 zip 条目本身，返回相对包根的路径清单。"""
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()

    names = [info.filename for info in infos]
    relatives: list = []
    prefix_bad: list = []
    unsafe: list = []
    mode_bad: list = []

    for info in infos:
        name = info.filename
        if not name.startswith(ARCHIVE_PREFIX + "/"):
            prefix_bad.append(name)
        else:
            relatives.append(name[len(ARCHIVE_PREFIX) + 1:])
        reason = unsafe_reason(name)
        if reason:
            unsafe.append(f"{name}（{reason}）")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            mode_bad.append(f"{name}（符号链接）")
        elif mode and (mode & 0o7777) != 0o644:
            mode_bad.append(f"{name}（权限位 {oct(mode & 0o7777)}）")

    checks.add(
        f"顶层路径统一为 {ARCHIVE_PREFIX}/",
        not prefix_bad,
        "越界条目：" + ", ".join(prefix_bad[:5]))
    checks.add(
        "条目路径安全（无绝对路径 / .. / 反斜杠 / 控制字符）",
        not unsafe,
        "；".join(unsafe[:5]))
    seen: set = set()
    duplicates: list = []
    for name in names:
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    checks.add("无重复路径", not duplicates, ", ".join(sorted(set(duplicates))[:5]))
    checks.add(
        "条目均为常规文件且权限位统一 0644",
        not mode_bad,
        "；".join(mode_bad[:5]))
    return relatives


def check_contents(relatives: list, checks: Checks) -> None:
    """必需文件齐全 + 私有/开发文件缺失 + 与白名单完全一致。"""
    present = set(relatives)

    missing = [name for name in REQUIRED_FILES if name not in present]
    checks.add(
        f"必需文件齐全（{len(REQUIRED_FILES)} 个）",
        not missing,
        "缺少：" + ", ".join(missing))

    leaked: list = []
    for name in sorted(present):
        parts = name.split("/")
        base = parts[-1]
        if name in FORBIDDEN_NAMES or base in FORBIDDEN_NAMES:
            leaked.append(name)
            continue
        if any(part in FORBIDDEN_DIRS for part in parts):
            leaked.append(name)
            continue
        if any(base.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
            leaked.append(name)
    checks.add(
        "不含用户私有 / 开发文件（配置、历史、锁、eval、tests、tools、dist 等）",
        not leaked,
        ", ".join(leaked[:8]))

    expected = {path.relative_to(ROOT).as_posix() for path in collect_files()}
    extra = sorted(present - expected)
    absent = sorted(expected - present)
    checks.add(
        "包内文件与白名单完全一致",
        not extra and not absent,
        "多出：" + ", ".join(extra[:5]) + "；缺少：" + ", ".join(absent[:5]))


def check_style_files(relatives: list, checks: Checks) -> None:
    """styles.json 声明的每个风格都要在包里，反之亦然。"""
    present = set(relatives)
    data = json.loads((ROOT / "config" / "styles.json").read_text(encoding="utf-8"))
    styles = data.get("styles", [])
    missing = [s.get("id", "?") for s in styles if s.get("file") not in present]
    checks.add(
        f"styles.json 声明的 {len(styles)} 个风格文件都在包内",
        not missing,
        "缺少：" + ", ".join(missing[:8]))
    packaged = sorted(name for name in present if name.startswith("styles/"))
    checks.add(
        f"包内风格文件数与 styles.json 一致（{len(styles)} 个）",
        len(packaged) == len(styles),
        f"包内 {len(packaged)} 个，声明 {len(styles)} 个")


def check_no_leaks(archive_path: Path, checks: Checks) -> None:
    """包内文本不得含机器路径或密钥形态。"""
    machine: list = []
    secret: list = []
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.file_size > 2 * 1024 * 1024:
                continue
            if not info.filename.lower().endswith((".md", ".json", ".py", ".txt")):
                continue
            try:
                text = archive.read(info).decode("utf-8")
            except (UnicodeDecodeError, RuntimeError):
                continue
            for pattern in MACHINE_PATH_PATTERNS:
                if pattern in text:
                    machine.append(f"{info.filename}（{pattern}）")
            for pattern in SECRET_PATTERNS:
                if re.search(pattern, text):
                    secret.append(f"{info.filename}（{pattern}）")
    checks.add("包内不含机器特定路径", not machine, ", ".join(machine[:5]))
    checks.add("包内不含密钥形态内容", not secret, ", ".join(secret[:5]))


def check_install(archive_path: Path, checks: Checks) -> None:
    """解压到临时目录，跑一遍最小使用流程——只验证 zip 存在是不够的。"""
    with tempfile.TemporaryDirectory(prefix="tone-particles-install-") as tmp:
        workdir = Path(tmp)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(workdir)
        package_root = workdir / ARCHIVE_PREFIX
        checks.add(
            f"解压后得到 {ARCHIVE_PREFIX}/ 目录",
            package_root.is_dir(),
            f"解压目录内容：{sorted(p.name for p in workdir.iterdir())[:5]}")
        if not package_root.is_dir():
            return

        cases = [
            ("最小流程：compose_prompt --main S04（退出码 0 且输出非空）",
             [sys.executable, str(package_root / "scripts" / "compose_prompt.py"),
              "--main", "S04"], ""),
            ("最小流程：compose_prompt --main S04 --json（输出可解析）",
             [sys.executable, str(package_root / "scripts" / "compose_prompt.py"),
              "--main", "S04", "--json"], "json"),
            ("最小流程：pick_style --catalog（退出码 0 且输出非空）",
             [sys.executable, str(package_root / "scripts" / "pick_style.py"),
              "--catalog"], ""),
            ("最小流程：check_density --help（退出码 0 且输出非空）",
             [sys.executable, str(package_root / "scripts" / "check_density.py"),
              "--help"], ""),
        ]
        for name, argv, expect_json in cases:
            proc = subprocess.run(
                argv, cwd=str(workdir), capture_output=True, text=True, timeout=120)
            ok = proc.returncode == 0 and proc.stdout.strip() != ""
            detail = ""
            if not ok:
                detail = f"退出码 {proc.returncode}；{(proc.stderr or proc.stdout)[-200:]}"
            elif expect_json == "json":
                try:
                    json.loads(proc.stdout)
                except json.JSONDecodeError as exc:
                    ok = False
                    detail = f"JSON 解析失败：{exc}"
            checks.add(name, ok, detail)


def zip_entries(archive_path: Path) -> list:
    """zip 内每个文件的路径、大小与内容 SHA-256。"""
    entries: list = []
    with zipfile.ZipFile(archive_path) as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            data = archive.read(info)
            entries.append({
                "path": info.filename,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    return entries


def write_manifest(version: str, archive_path: Path, entries: list) -> tuple:
    """写出内容清单与 SHA-256 校验和文件。"""
    dist = ROOT / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    manifest_path = dist / f"tone-particles-{version}.manifest.json"
    checksum_path = dist / f"tone-particles-{version}.zip.sha256"
    package_sha = sha256_path(archive_path)
    manifest = {
        "package": archive_path.name,
        "version": version,
        "prefix": f"{ARCHIVE_PREFIX}/",
        "sha256": package_sha,
        "size": archive_path.stat().st_size,
        "file_count": len(entries),
        "generated_by": "tools/package.py --verify",
        "files": entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checksum_path.write_text(f"{package_sha}  {archive_path.name}\n", encoding="utf-8")
    return manifest_path, checksum_path


def verify(version: str) -> int:
    checks = Checks()
    archive_path = ROOT / "dist" / f"tone-particles-{version}.zip"
    build_to(version, archive_path)

    with tempfile.TemporaryDirectory(prefix="tone-particles-repro-") as tmp:
        second = Path(tmp) / archive_path.name
        build_to(version, second)
        first_sha = sha256_path(archive_path)
        second_sha = sha256_path(second)
    checks.add(
        "可复现：同一工作树连续两次构建 SHA-256 一致",
        first_sha == second_sha,
        f"{first_sha} != {second_sha}")

    relatives = inspect_archive(archive_path, checks)
    check_contents(relatives, checks)
    check_style_files(relatives, checks)
    check_no_leaks(archive_path, checks)
    check_install(archive_path, checks)

    manifest_path, checksum_path = write_manifest(
        version, archive_path, zip_entries(archive_path))
    checks.add(
        "清单与 SHA-256 校验和文件已生成",
        manifest_path.exists() and checksum_path.exists(),
        f"{manifest_path} / {checksum_path}")
    code = checks.finish()
    print(f"包 SHA-256：{first_sha}")
    print(f"清单：{manifest_path.relative_to(ROOT).as_posix()}")
    print(f"校验和：{checksum_path.relative_to(ROOT).as_posix()}")
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 skill 分发包")
    parser.add_argument("--check", action="store_true", help="只校验版本一致性，不写文件")
    parser.add_argument(
        "--verify", action="store_true",
        help="供应链校验：可复现性、内容清单、路径安全、解压最小安装、SHA-256 清单")
    args = parser.parse_args(argv)
    if args.check and args.verify:
        parser.error("--check 与 --verify 不能同时使用")

    version = read_version()
    check_version_consistency(version)
    if args.check:
        print(f"版本一致性 OK：{version}")
        return 0
    if args.verify:
        return verify(version)

    target, files = build(version)
    print(f"已构建 {target.relative_to(ROOT)}（{len(files)} 个文件，顶层 {ARCHIVE_PREFIX}/）")
    for path in files:
        print(f"  {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
