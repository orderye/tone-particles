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

from schemas import SCHEMAS, validate_arguments  # noqa: E402
from tools import TOOL_DESCRIPTIONS, Tools, call_tool  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "tone-particles"
SERVER_VERSION = "0.2.2"

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
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return make_error(request_id, INVALID_PARAMS, "params 必须是 JSON 对象。")

    if not method:
        return make_error(request_id, INVALID_REQUEST, "缺少 method。")
    if not isinstance(method, str):
        return make_error(request_id, INVALID_REQUEST, "method 必须是字符串。")

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
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return make_error(
                request_id, INVALID_PARAMS, "tools/call 的 arguments 必须是 JSON 对象。")
        if not name or not isinstance(name, str):
            return make_error(request_id, INVALID_PARAMS, "tools/call 缺少 name。")
        schema = SCHEMAS.get(name)
        if schema is None:
            # 未知工具是工具级错误：模型能读到并自我纠正。
            return make_response(request_id, {
                "content": [{"type": "text", "text": f"未知工具：{name}"}],
                "isError": True,
            })
        errors, unknown = validate_arguments(schema, arguments)
        if errors:
            return make_error(
                request_id, INVALID_PARAMS,
                f"工具 {name} 的参数不合法：{'；'.join(errors)}")
        if unknown:
            # 未知参数不静默丢弃。既有契约里「未知配置键」是工具级错误，
            # 这里保持同一形态，只是把丢弃换成显式报错。
            return make_response(request_id, {
                "content": [{
                    "type": "text",
                    "text": f"工具 {name} 收到未知参数：{'、'.join(sorted(unknown))}。"
                            f"可用参数：{'、'.join(sorted(schema.get('properties') or {}))}。",
                }],
                "isError": True,
            })
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
    """逐行处理 JSON-RPC 消息。

    stdout 只写协议响应：任何诊断信息都走 stderr。单个请求出错不能让整个进程
    退出——后续消息必须还能被处理。
    """
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
        try:
            response = handle_message(message, tools)
        except Exception as exc:  # noqa: BLE001 - 单条消息出错不应终止服务
            print(f"处理消息时出错：{type(exc).__name__}: {exc}", file=sys.stderr)
            response = make_error(
                message.get("id"), INTERNAL_ERROR,
                f"内部错误：{type(exc).__name__}")
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
