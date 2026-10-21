#!/usr/bin/env python3
"""配置读写的可靠性测试（纯标准库）。

覆盖阶段一任务 A 的验收点：
- 原子写入：不留半截 JSON，临时文件被清理
- 写前校验：非法配置不落盘，旧文件字节不变
- 写后校验：落盘内容仍可读
- 失败路径：只读目录写不进去时，旧配置保持可读
- 并发：多进程同时更新同一份配置，文件始终是合法 JSON，
  且互不相关的字段不会被覆盖
- 隔离：不同用户的配置与历史互不串线
- 未知字段策略：默认告警并保留，strict 模式下拒绝

运行：python3 tests/test_config.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import Runner  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _core  # noqa: E402

WORKER = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import _core
path, patch = sys.argv[2], json.loads(sys.argv[3])
_core.update_config_file(path, patch)
"""


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def tmp_files(directory: Path) -> list:
    """目录里残留的临时文件（原子写入用的中间文件）。"""
    return [item.name for item in directory.iterdir() if item.name.endswith(".tmp")]


def main() -> int:
    r = Runner("配置读写可靠性")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cfg_path = tmp_path / "user-config.json"

        # -- 原子写入 --------------------------------------------------------
        cfg = _core.normalize_config(_core.migrate_config({
            "mode": "rotate",
            "styles": [{"id": "S09", "weight": 2}, {"id": "S04", "weight": 1}],
        }))
        _core.save_config(cfg_path, cfg)
        r.check("写入后可回读", read_json(cfg_path)["mode"] == "rotate")
        r.check("写入后没有残留临时文件", tmp_files(tmp_path) == [], str(tmp_files(tmp_path)))
        if os.name != "nt":
            mode = cfg_path.stat().st_mode & 0o777
            r.check("用户配置权限收紧到 0600", mode == 0o600, oct(mode))

        # -- 写前校验：非法配置不落盘 ------------------------------------------
        before = cfg_path.read_bytes()
        try:
            _core.save_config(cfg_path, {"mode": "rotate", "styles": [{"id": "S09", "weight": 0}]})
        except SystemExit:
            r.check("非法权重被拒绝", True)
        else:
            r.check("非法权重被拒绝", False, "save_config 没有报错")
        r.check("非法配置写入后旧文件字节不变", cfg_path.read_bytes() == before)

        try:
            _core.save_config(cfg_path, {"mode": "hourly", "styles": [{"id": "S09"}]})
        except SystemExit:
            r.check("非法 mode 被拒绝", True)
        else:
            r.check("非法 mode 被拒绝", False, "save_config 没有报错")
        r.check("非法 mode 写入后旧文件字节不变", cfg_path.read_bytes() == before)

        # -- 未知字段策略 ----------------------------------------------------
        unknown_path = tmp_path / "unknown.json"
        unknown_path.write_text(json.dumps({
            "mode": "single", "styles": [{"id": "S09"}], "未来字段": {"x": 1},
        }, ensure_ascii=False), encoding="utf-8")
        warnings: list = []
        loaded = _core.normalize_config(
            _core.migrate_config(read_json(unknown_path)), warnings=warnings)
        report = _core.validate_config(loaded)
        r.check("未知字段默认是告警不是错误",
                not report["errors"] and any("未来字段" in item for item in report["warnings"]),
                str(report))
        strict_report = _core.validate_config(loaded, strict=True)
        r.check("strict 模式下未知字段变成错误",
                any("未来字段" in item for item in strict_report["errors"]),
                str(strict_report))
        r.check("未知字段不会被丢弃", loaded.get("未来字段") == {"x": 1})

        # -- 越界数值：夹取但留痕 ----------------------------------------------
        clamped: list = []
        out = _core.normalize_config({
            "mode": "single", "styles": [{"id": "S09"}],
            "switch": {"no_repeat_window": 99, "turns": 0},
        }, warnings=clamped)
        r.check("去重窗口被夹到 10", out["switch"]["no_repeat_window"] == 10)
        r.check("轮数被夹到 1", out["switch"]["turns"] == 1)
        r.check("夹取有可观察的告警", len(clamped) == 2, str(clamped))

        # -- 归一化不改动调用方的对象 ------------------------------------------
        original = {"mode": "single", "styles": ["s09"], "switch": {"turns": 9}}
        snapshot = json.dumps(original, sort_keys=True)
        _core.normalize_config(_core.migrate_config(original))
        r.check("normalize/migrate 不改动传入的字典",
                json.dumps(original, sort_keys=True) == snapshot, str(original))

        # -- 只读目录：写不进去时旧配置保持可读 ----------------------------------
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            ro_dir = tmp_path / "readonly"
            ro_dir.mkdir()
            ro_cfg = ro_dir / "user-config.json"
            _core.save_config(ro_cfg, cfg)
            os.chmod(ro_dir, 0o500)
            try:
                _core.save_config(ro_cfg, {"mode": "single", "styles": [{"id": "S01"}]})
            except (OSError, SystemExit):
                r.check("只读目录下写入失败会报错", True)
            else:
                r.check("只读目录下写入失败会报错", False, "写入没有报错")
            finally:
                os.chmod(ro_dir, 0o700)
            r.check("写入失败后旧配置仍可读",
                    read_json(ro_cfg)["mode"] == "rotate")
            r.check("写入失败后没有残留临时文件",
                    tmp_files(ro_dir) == [], str(tmp_files(ro_dir)))
        else:
            r.check("只读目录下写入失败会报错（以 root 运行，跳过）", True)
            r.check("写入失败后旧配置仍可读（以 root 运行，跳过）", True)
            r.check("写入失败后没有残留临时文件（以 root 运行，跳过）", True)

        # -- 并发：多进程同时更新 ----------------------------------------------
        conc_path = tmp_path / "concurrent.json"
        _core.save_config(conc_path, cfg)
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        workers = []
        for index in range(4):
            patch = {"switch": {"turns": index + 1}}
            workers.append(subprocess.Popen(
                [sys.executable, "-c", WORKER, str(scripts), str(conc_path),
                 json.dumps(patch)]))
        for index in range(2):
            patch = {"kaomoji": {"level": "normal" if index else "light"}}
            workers.append(subprocess.Popen(
                [sys.executable, "-c", WORKER, str(scripts), str(conc_path),
                 json.dumps(patch)]))
        invalid_seen = False
        while any(worker.poll() is None for worker in workers):
            try:
                json.loads(conc_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                invalid_seen = True
            except FileNotFoundError:
                invalid_seen = True
            time.sleep(0.005)
        codes = [worker.wait() for worker in workers]
        r.check("并发写入的子进程全部成功", all(code == 0 for code in codes), str(codes))
        final = read_json(conc_path)
        r.check("并发写入过程中文件始终是合法 JSON", not invalid_seen)
        r.check("并发写入后 switch.turns 合法",
                isinstance(final["switch"]["turns"], int)
                and 1 <= final["switch"]["turns"] <= 20, str(final["switch"]))
        r.check("并发写入后不相关的字段没有被覆盖",
                final["kaomoji"]["level"] in {"light", "normal"}
                and final["styles"][0]["id"] == "S09",
                str(final))
        r.check("并发写入后没有残留临时文件", tmp_files(tmp_path) == [], str(tmp_files(tmp_path)))

        # -- 锁本身：拿不到锁要报错，不能静默降级 --------------------------------
        lock_path = tmp_path / "locked.json"
        _core.save_config(lock_path, cfg)
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys,time;sys.path.insert(0,sys.argv[1]);import _core;"
             "\nwith _core.config_lock(sys.argv[2], timeout=10):\n    print('locked',flush=True)\n    time.sleep(3)\n",
             str(scripts), str(lock_path)],
            stdout=subprocess.PIPE)
        try:
            holder.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        deadline = time.time() + 5
        blocked = False
        while time.time() < deadline:
            try:
                with _core.config_lock(lock_path, timeout=0.2):
                    break
            except SystemExit:
                blocked = True
                break
        r.check("锁被占用时报错而不是静默写入", blocked)
        holder.kill()
        holder.wait()

        # -- 用户隔离 ----------------------------------------------------------
        a_dir = tmp_path / "user-a"
        b_dir = tmp_path / "user-b"
        a_dir.mkdir()
        b_dir.mkdir()
        a_cfg, b_cfg = a_dir / "user-config.json", b_dir / "user-config.json"
        _core.save_config(a_cfg, {"mode": "single", "styles": [{"id": "S09"}]})
        _core.save_config(b_cfg, {"mode": "single", "styles": [{"id": "S17"}]})
        _core.save_history(a_dir / "tone-history.json", ["S09", "S04"])
        _core.save_history(b_dir / "tone-history.json", ["S17"])
        r.check("A 用户的配置不被 B 用户影响", read_json(a_cfg)["styles"][0]["id"] == "S09")
        r.check("A 用户的历史不被 B 用户影响",
                read_json(a_dir / "tone-history.json") == ["S09", "S04"])
        r.check("B 用户的历史独立",
                read_json(b_dir / "tone-history.json") == ["S17"])

        # -- update_config_file 的合并语义 --------------------------------------
        merged_path = tmp_path / "merged.json"
        _core.save_config(merged_path, {
            "mode": "rotate",
            "styles": [{"id": "S09", "weight": 2}],
            "kaomoji": {"enabled": True, "level": "normal"},
        })
        result = _core.update_config_file(merged_path, {"density": "strong"})
        r.check("update_config_file 只改被点名的字段",
                result["density"] == "strong"
                and result["kaomoji"]["level"] == "normal"
                and result["styles"][0]["weight"] == 2, str(result))
        r.check("update_config_file 的结果已落盘",
                read_json(merged_path)["density"] == "strong")
        try:
            _core.update_config_file(merged_path, {"denstiy": "light"})
        except SystemExit:
            r.check("update_config_file 拒绝未知键", True)
        else:
            r.check("update_config_file 拒绝未知键", False, "没有报错")
        r.check("被拒绝的写入不改变文件",
                read_json(merged_path)["density"] == "strong")

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
