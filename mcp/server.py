#!/usr/bin/env python3
"""语气助词 Skill 的 MCP 服务（stdio 传输）。

零依赖：JSON-RPC 2.0 over stdio，纯标准库实现。

协议方法：
    initialize              握手
    notifications/initialized 客户端通知，不回响应
    tools/list              列出四个工具
    tools/call              调用工具
    ping                    连通性检查
    resources/list、prompts/list  空列表，供只探测这两项的客户端使用

用法：
    python3 mcp/server.py --config /path/user-config.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from schemas import SCHEMAS  # noqa: E402
from tools import TOOL_DESCRIPTIONS, Tools, call_tool  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "tone-particles"
SERVER_VERSION = "0.2.1"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def make_response(request_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_message(message: dict, tools: Tools):
    """处理一条 JSON-RPC 消息。通知类返回 None。"""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if not method:
        return make_error(request_id, INVALID_REQUEST, "缺少 method。")

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        return make_response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "ping":
        return make_response(request_id, {})

    if method == "tools/list":
        return make_response(request_id, {
            "tools": [
                {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "inputSchema": SCHEMAS[name],
                }
                for name in SCHEMAS
            ]
        })

    if method == "resources/list":
        return make_response(request_id, {"resources": []})

    if method == "prompts/list":
        return make_response(request_id, {"prompts": []})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return make_error(request_id, INVALID_PARAMS, "tools/call 缺少 name。")
        required = SCHEMAS.get(name, {}).get("required", [])
        missing = [item for item in required if item not in arguments]
        if missing:
            return make_error(
                request_id, INVALID_PARAMS,
                f"工具 {name} 缺少必填参数：{'、'.join(missing)}")
        try:
            text = call_tool(tools, name, arguments)
        except SystemExit as exc:
            # 核心层的配置错误是可预期的，转成工具级错误而不是协议错误
            return make_response(request_id, {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            })
        except Exception as exc:  # noqa: BLE001
            return make_response(request_id, {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            })
        return make_response(request_id, {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        })

    return make_error(request_id, METHOD_NOT_FOUND, f"未知方法：{method}")


def serve(tools: Tools, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            stdout.write(json.dumps(
                make_error(None, PARSE_ERROR, f"JSON 解析失败：{exc}"),
                ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        if not isinstance(message, dict):
            stdout.write(json.dumps(
                make_error(None, INVALID_REQUEST, "消息必须是 JSON 对象。"),
                ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        response = handle_message(message, tools)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="语气助词 Skill 的 MCP 服务")
    parser.add_argument("--config", help="用户配置路径，默认 skill 目录下的 config/user-config.json")
    parser.add_argument("--root", help="skill 根目录，默认自动定位")
    args = parser.parse_args(argv)

    tools = Tools(config_path=args.config, root=args.root)
    return serve(tools)


if __name__ == "__main__":
    sys.exit(main())
