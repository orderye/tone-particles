#!/usr/bin/env python3
"""MCP 服务的自检。

不引 pytest，纯标准库，直接 `python3 mcp/tests/test_mcp.py` 运行。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MCP_ROOT))

from server import handle_message  # noqa: E402
from tools import Tools  # noqa: E402

PASSED = []
FAILED = []


def check(name: str, condition, detail: str = ""):
    if condition:
        PASSED.append(name)
    else:
        FAILED.append(f"{name}{'：' + detail if detail else ''}")


def call(tools, method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return handle_message(message, tools)


def tool_result(response):
    return json.loads(response["result"]["content"][0]["text"])


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="tone-mcp-test-"))
    config_path = workdir / "user-config.json"
    tools = Tools(config_path=config_path)

    # 1. 握手
    response = call(tools, "initialize")
    result = response.get("result", {})
    check("initialize 返回协议版本", result.get("protocolVersion") == "2024-11-05")
    check("initialize 声明 tools 能力", "tools" in result.get("capabilities", {}))
    check("initialize 带服务信息", result.get("serverInfo", {}).get("name") == "tone-particles")

    # 2. 通知不回响应
    check("通知不产生响应",
          handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, tools) is None)

    # 3. 工具清单
    response = call(tools, "tools/list")
    tools_list = response.get("result", {}).get("tools", [])
    names = [item["name"] for item in tools_list]
    check("tools/list 返回 4 个工具",
          names == ["list_styles", "get_style_prompt", "set_user_style", "pick_next_style"],
          str(names))
    check("每个工具都有入参 schema",
          all(item.get("inputSchema", {}).get("type") == "object" for item in tools_list))
    check("每个工具都有描述",
          all(item.get("description") for item in tools_list))

    # 4. list_styles
    response = call(tools, "tools/call", {"name": "list_styles", "arguments": {}})
    payload = tool_result(response)
    check("list_styles 返回 21 个风格", payload["count"] == 21, str(payload.get("count")))
    check("list_styles 返回 6 个分组", len(payload["groups"]) == 6)
    check("list_styles 默认不带全文",
          all("prompt" not in item for item in payload["styles"]))

    response = call(tools, "tools/call", {
        "name": "list_styles", "arguments": {"group": "软萌可爱"}})
    payload = tool_result(response)
    check("list_styles 支持按分组过滤",
          payload["count"] > 0 and all(item["group"] == "软萌可爱" for item in payload["styles"]))

    response = call(tools, "tools/call", {
        "name": "list_styles", "arguments": {"include_prompt": True}})
    payload = tool_result(response)
    check("list_styles 可选带全文",
          all(item.get("prompt") for item in payload["styles"]))

    # 5. get_style_prompt
    response = call(tools, "tools/call", {
        "name": "get_style_prompt", "arguments": {"style_id": "S09"}})
    payload = tool_result(response)
    check("get_style_prompt 返回 single 模式", payload["mode"] == "single")
    check("get_style_prompt 带主风格全文", "## 主风格全文（S09 傲娇）" in payload["prompt"])
    check("get_style_prompt 给出密度区间", len(payload["density_range"]) == 2)

    response = call(tools, "tools/call", {
        "name": "get_style_prompt",
        "arguments": {"style_id": "S09", "accents": ["S04"], "weights": [3, 2]}})
    payload = tool_result(response)
    check("get_style_prompt 支持融合", payload["mode"] == "blend")
    check("融合保留权重", [m["weight"] for m in payload["members"]] == [3, 2])
    check("融合比例写进提示词", "60%" in payload["prompt"])

    response = call(tools, "tools/call", {
        "name": "get_style_prompt",
        "arguments": {"style_id": "S20", "variant": "strict"}})
    payload = tool_result(response)
    check("get_style_prompt 支持子模式", payload["variants"] == {"S20": "strict"})
    check("子模式写进提示词", "严厉型" in payload["prompt"])

    response = call(tools, "tools/call", {
        "name": "get_style_prompt",
        "arguments": {"style_id": "S09", "density": "strong"}})
    payload = tool_result(response)
    check("get_style_prompt 支持密度档位", payload["density"] == "strong")

    # 6. 未知风格 id 要报错而不是静默通过
    response = call(tools, "tools/call", {
        "name": "get_style_prompt", "arguments": {"style_id": "S99"}})
    check("未知风格 id 报工具级错误",
          response.get("result", {}).get("isError") is True)

    # 7. set_user_style
    response = call(tools, "tools/call", {
        "name": "set_user_style",
        "arguments": {
            "mode": "rotate",
            "styles": [{"id": "S09", "weight": 2}, {"id": "S04", "weight": 1}],
            "density": "strong",
            "kaomoji": {"enabled": True, "level": "normal"},
        }})
    payload = tool_result(response)
    check("set_user_style 写入成功", payload["saved"] is True)
    check("set_user_style 落盘", config_path.exists())
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    check("配置模式已写入", saved["mode"] == "rotate")
    check("配置风格池已写入", [s["id"] for s in saved["styles"]] == ["S09", "S04"])
    check("配置权重已写入", saved["styles"][0]["weight"] == 2)
    check("配置颜文字已写入", saved["kaomoji"]["enabled"] is True)

    # 8. pick_next_style
    response = call(tools, "tools/call", {"name": "pick_next_style", "arguments": {}})
    payload = tool_result(response)
    check("pick_next_style 返回主风格", payload["main"] in {"S09", "S04"})
    check("pick_next_style 带中文名", payload["main_name"] in {"傲娇", "邻家"})
    check("pick_next_style 带回退口径", "notes" in payload)

    first = call(tools, "tools/call", {
        "name": "pick_next_style", "arguments": {"seed": 42}})["result"]
    second = call(tools, "tools/call", {
        "name": "pick_next_style", "arguments": {"seed": 42}})["result"]
    check("同一 seed 结果可复现", first == second)

    # 9. 协议层错误
    response = call(tools, "no/such/method")
    check("未知方法返回 -32601", response.get("error", {}).get("code") == -32601)

    response = call(tools, "tools/call", {"name": "get_style_prompt", "arguments": {}})
    check("缺必填参数返回 -32602", response.get("error", {}).get("code") == -32602)

    response = call(tools, "tools/call", {"name": "nope", "arguments": {}})
    check("未知工具报工具级错误",
          response.get("result", {}).get("isError") is True)

    response = handle_message({"jsonrpc": "2.0", "id": 9, "method": "ping"}, tools)
    check("ping 有响应", response.get("result") == {})

    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for item in FAILED:
        print(f"  ✗ {item}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
