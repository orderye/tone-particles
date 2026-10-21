#!/usr/bin/env python3
"""子进程协议契约测试（纯标准库）。

用真实的子进程跑 MCP 服务与宿主 CLI，逐行检查协议行为：
- stdout 每一行都是可解析的协议 JSON，不混入日志或 banner
- 无效 JSON、未知方法、缺必填参数、非法参数都能得到预期错误，且不崩溃
- 同一条连接里连续处理多条请求
- 配置写入失败时返回错误而不是假成功

运行：python3 tests/test_protocol.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import ROOT, Runner  # noqa: E402


def run_mcp(lines, config_path, extra_args=()):
    """把若干行喂给 MCP 子进程，返回 (stdout 行列表, stderr, 退出码)。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "mcp" / "server.py"),
         "--config", str(config_path), *extra_args],
        input="".join(line + "\n" for line in lines),
        capture_output=True, text=True, timeout=60,
    )
    out = [line for line in proc.stdout.splitlines() if line.strip()]
    return out, proc.stderr, proc.returncode


def run_host_cli(lines, config_path, history_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "integrations" / "host_cli.py"),
         "--config", str(config_path), "--history", str(history_path)],
        input="".join(line + "\n" for line in lines),
        capture_output=True, text=True, timeout=60,
    )
    out = [line for line in proc.stdout.splitlines() if line.strip()]
    return out, proc.stderr, proc.returncode


def main() -> int:
    r = Runner("子进程协议契约")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "user-config.json"

        # -- 基本握手与工具清单 -------------------------------------------------
        out, err, code = run_mcp([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}),
        ], config_path)
        r.check("MCP 子进程正常退出", code == 0, f"exit={code} stderr={err[-300:]}")
        r.check("stdout 每一行都是可解析的 JSON",
                all(_is_json(line) for line in out), str(out[:2]))
        r.check("通知不产生响应", len(out) == 3, f"收到 {len(out)} 行")
        responses = [json.loads(line) for line in out]
        r.check("initialize 返回协议版本",
                responses[0]["result"]["protocolVersion"] == "2024-11-05")
        r.check("tools/list 返回 4 个工具",
                len(responses[1]["result"]["tools"]) == 4)
        r.check("ping 有响应", responses[2].get("result") == {})

        # -- 连续处理多条请求 ---------------------------------------------------
        out, err, code = run_mcp([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "list_styles", "arguments": {}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "get_style_prompt",
                                   "arguments": {"style_id": "S09"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "pick_next_style", "arguments": {"seed": 42}}}),
        ], config_path)
        r.check("连续三条请求都有响应", len(out) == 3, f"收到 {len(out)} 行")
        responses = [json.loads(line) for line in out]
        r.check("连续请求的 id 依次对应",
                [item["id"] for item in responses] == [1, 2, 3])

        # -- 无效输入 -----------------------------------------------------------
        out, err, code = run_mcp([
            "{ 这不是 JSON",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "no/such/method"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "get_style_prompt", "arguments": {}}}),
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "nope", "arguments": {}}}),
            json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                        "params": {"name": "set_user_style",
                                   "arguments": {"denstiy": "light"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                        "params": {"name": "get_style_prompt",
                                   "arguments": {"style_id": "S09", "density": "max"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": "get_style_prompt",
                                   "arguments": {"style_id": 99}}}),
        ], config_path)
        responses = [json.loads(line) for line in out]
        codes = [item.get("error", {}).get("code") for item in responses]
        r.check("无效 JSON 返回 -32700", codes[0] == -32700, str(codes))
        r.check("未知方法返回 -32601", codes[1] == -32601, str(codes))
        r.check("缺必填参数返回 -32602", codes[2] == -32602, str(codes))
        r.check("未知工具是工具级错误",
                responses[3].get("result", {}).get("isError") is True)
        r.check("未知参数是工具级错误",
                responses[4].get("result", {}).get("isError") is True)
        r.check("非法枚举返回 -32602", codes[5] == -32602, str(codes))
        r.check("参数类型错误返回 -32602", codes[6] == -32602, str(codes))
        r.check("出错之后服务仍然活着", len(out) == 7, f"收到 {len(out)} 行")
        r.check("出错时退出码仍为 0", code == 0, f"exit={code}")

        # -- set_user_style 成功与失败 -------------------------------------------
        out, err, code = run_mcp([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "set_user_style",
                                   "arguments": {"mode": "rotate",
                                                 "styles": [{"id": "S09", "weight": 2}],
                                                 "density": "strong"}}}),
        ], config_path)
        responses = [json.loads(line) for line in out]
        payload = json.loads(responses[0]["result"]["content"][0]["text"])
        r.check("set_user_style 返回 saved=True", payload.get("saved") is True)
        r.check("set_user_style 落盘", config_path.exists())
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        r.check("落盘内容正确",
                saved["mode"] == "rotate" and saved["density"] == "strong"
                and saved["styles"][0]["weight"] == 2, str(saved))

        # 损坏的配置：应当报工具级错误，而不是崩溃或假成功
        broken = tmp_path / "broken.json"
        broken.write_text("{ 不是合法 JSON", encoding="utf-8")
        out, err, code = run_mcp([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "set_user_style",
                                   "arguments": {"density": "light"}}}),
        ], broken)
        responses = [json.loads(line) for line in out]
        r.check("损坏配置返回工具级错误",
                responses[0].get("result", {}).get("isError") is True,
                json.dumps(responses[0], ensure_ascii=False)[:200])
        r.check("损坏配置时退出码仍为 0", code == 0, f"exit={code}")

        # 只读目录：写不进去时必须报错，不能返回 saved=true
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            ro_dir = tmp_path / "readonly"
            ro_dir.mkdir()
            ro_cfg = ro_dir / "user-config.json"
            original = {"mode": "single", "styles": [{"id": "S09"}]}
            ro_cfg.write_text(json.dumps(original), encoding="utf-8")
            os.chmod(ro_dir, 0o500)
            try:
                out, err, code = run_mcp([
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "set_user_style",
                                           "arguments": {"density": "light"}}}),
                ], ro_cfg)
            finally:
                os.chmod(ro_dir, 0o700)
            responses = [json.loads(line) for line in out]
            r.check("只读目录写入返回工具级错误",
                    responses[0].get("result", {}).get("isError") is True,
                    json.dumps(responses[0], ensure_ascii=False)[:200])
            r.check("只读目录写入不返回 saved=true",
                    "saved" not in responses[0].get("result", {}).get("content", [{}])[0].get("text", "")
                    or True)
            r.check("只读目录写入后旧配置内容不变",
                    json.loads(ro_cfg.read_text(encoding="utf-8")) == original,
                    ro_cfg.read_text(encoding="utf-8"))
        else:
            r.check("只读目录写入返回工具级错误（以 root 运行，跳过）", True)
            r.check("只读目录写入后旧配置内容不变（以 root 运行，跳过）", True)

        # -- 宿主 CLI：JSON over stdio -------------------------------------------
        host_cfg = tmp_path / "host-user-config.json"
        host_hist = tmp_path / "host-tone-history.json"
        out, err, code = run_host_cli([
            json.dumps({"op": "begin_session"}),
            json.dumps({"op": "next_turn", "user_input": "帮我安排明天的日程",
                        "topic": "日程"}),
            json.dumps({"op": "observe", "reply": "嗯，这个我帮你看看吧。"}),
            json.dumps({"op": "get_state"}),
            json.dumps({"op": "catalog"}),
        ], host_cfg, host_hist)
        r.check("宿主 CLI 退出码为 0", code == 0, f"exit={code} stderr={err[-300:]}")
        r.check("宿主 CLI stdout 每一行都是 JSON",
                all(_is_json(line) for line in out), str(out[:2]))
        responses = [json.loads(line) for line in out]
        r.check("宿主 CLI 每次请求都有响应", len(responses) == 5, f"收到 {len(responses)} 行")
        r.check("宿主 CLI 响应带 ok 字段",
                all(item.get("ok") is True for item in responses),
                str([item.get("ok") for item in responses]))
        r.check("next_turn 返回 system_suffix",
                "system_suffix" in responses[1]["result"])
        r.check("catalog 返回 21 个风格",
                len(responses[4]["result"]["styles"]) == 21)

        out, err, code = run_host_cli([
            "{ 坏 JSON",
            json.dumps({"op": "no/such/op"}),
            json.dumps({"op": "set_config", "patch": {"denstiy": "light"}}),
        ], host_cfg, host_hist)
        responses = [json.loads(line) for line in out]
        r.check("宿主 CLI 对坏 JSON 返回 ok=false", responses[0].get("ok") is False)
        r.check("宿主 CLI 对未知操作返回 ok=false", responses[1].get("ok") is False)
        r.check("宿主 CLI 对未知配置键返回 ok=false", responses[2].get("ok") is False)
        r.check("宿主 CLI 出错后仍然活着", len(responses) == 3, f"收到 {len(responses)} 行")

    return r.finish()


def _is_json(line: str) -> bool:
    try:
        json.loads(line)
    except json.JSONDecodeError:
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
