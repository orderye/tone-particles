#!/usr/bin/env python3
"""语境策略与向后兼容的合同测试（纯标准库）。

覆盖阶段三的验收点：
- 场景判断是确定性的、可解释的（给出 reason code）
- 危机硬规则不会被配置或宿主元数据关闭
- 「任务是这类东西」与「闲聊里提到这类东西」分得开
- 旧调用方式继续可用：必填参数、返回字段、四种模式都不变
- 融合冲突按「安全 > 主风格 > 副风格」的确定性顺序解决

运行：python3 tests/test_context.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import ROOT, Runner  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "integrations"))

import _context  # noqa: E402
import _core  # noqa: E402
import compose_prompt  # noqa: E402
from host_adapter import ToneHost  # noqa: E402


def write_config(path: Path, **overrides) -> None:
    cfg = {
        "version": 1,
        "mode": "single",
        "styles": [{"id": "S09", "weight": 1}],
        "density": "standard",
        "switch": {"granularity": "per_message", "no_repeat_window": 3, "locked": False},
        "scene_adapt": True,
        "kaomoji": {"enabled": False, "level": "light"},
        "emoji": "style_default",
        "paused": False,
    }
    cfg.update(overrides)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    r = Runner("语境策略与合同")

    # -- 场景判断 ------------------------------------------------------------
    cases = [
        ("我不想活了，活着没意思，今晚就结束算了。", "crisis"),
        ("我最近有自杀的念头。", "crisis"),
        ("这 bug 我想死了，改了一整天。", "normal"),
        ("今天写代码好累啊。", "normal"),
        ("帮我看看这段 Python 代码报了个 KeyError 是哪里的问题\n```python\nx = 1\n```",
         "code"),
        ("这个正则表达式为什么匹配不到我要的内容？```js\nconst re = /x/\n```", "code"),
        ("帮我做一张各城市房价对比表。", "table"),
        ("我最近总是失眠，还有点心悸，要吃点什么药？", "high_risk"),
        ("帮我写一封拒绝这个面试邀约的邮件。", "formal"),
        ("帮我整理一份读书笔记的提纲。", "formal"),
        ("前端接口偶尔返回 504，怎么排查？", "error_steps"),
        ("今天被上司当众批评了，感觉特别难受。", "low_mood"),
        ("连续加班两周之后，我突然对什么都提不起兴趣。", "low_mood"),
        ("最近工作忙得脚不沾地，连周末都在加班。", "normal"),
        ("我养的猫今天把我的键盘按坏了。", "normal"),
        ("邮件系统怎么配置？", "normal"),
        ("Please help me write a Python script.", "non_chinese"),
    ]
    for text, expected in cases:
        got = _context.detect(text)
        r.check(f"场景判断：{expected}｜{text[:18]}",
                got == expected, f"实际 {got}")

    r.check("场景判断是确定性的",
            _context.detect("帮我写一封邮件") == _context.detect("帮我写一封邮件"))
    r.check("空输入归为普通对话", _context.detect("") == "normal")

    # -- 决策结构 ------------------------------------------------------------
    decision = _context.resolve("帮我做一张各城市房价对比表。")
    r.check("决策带 reason code", decision["reason_code"] == "table", str(decision))
    r.check("决策带可读理由", bool(decision["reason"]) and "表格" in decision["reason"])
    r.check("表格场景降到轻档", decision["density_level"] == "light")
    r.check("表格场景不关风格", decision["style_off"] is False)
    r.check("自动检测标记为 auto", decision["source"] == "auto")

    # -- 显式元数据覆盖 ------------------------------------------------------
    decision = _context.resolve("帮我做一张表", explicit={"scene": "formal"})
    r.check("显式场景覆盖自动检测", decision["scene"] == "formal", str(decision))
    r.check("显式覆盖标记为 explicit", decision["source"] == "explicit")

    decision = _context.resolve("普通闲聊", explicit={"scene": "code"})
    r.check("显式指定代码场景生效", decision["scene"] == "code")

    # -- 危机硬规则不可被覆盖 --------------------------------------------------
    decision = _context.resolve("我不想活了", explicit={"scene": "normal"})
    r.check("显式元数据不能盖掉危机",
            decision["scene"] == "crisis" and decision["style_off"] is True,
            str(decision))
    decision = _context.resolve("我不想活了", scene_adapt=False)
    r.check("关掉自动分类也不能关掉危机",
            decision["scene"] == "crisis" and decision["style_off"] is True,
            str(decision))

    # -- 自动分类可关闭 --------------------------------------------------------
    decision = _context.resolve("帮我做一张各城市房价对比表。", scene_adapt=False)
    r.check("scene_adapt=False 关闭自动分类",
            decision["scene"] == "normal" and decision["source"] == "disabled",
            str(decision))
    decision = _context.resolve("帮我做一张各城市房价对比表。", scene_adapt=False,
                                explicit={"scene": "table"})
    r.check("关掉自动分类后显式元数据仍然生效",
            decision["scene"] == "table" and decision["source"] == "explicit",
            str(decision))

    # -- 未知场景 -------------------------------------------------------------
    try:
        _context.resolve("x", explicit={"scene": "不存在的场景"})
    except SystemExit:
        r.check("未知场景报错", True)
    else:
        r.check("未知场景报错", False, "没有报错")

    # -- 提示词里的语境段落 ----------------------------------------------------
    payload = compose_prompt.compose([("S09", 1)], None, "light", None,
                                      _context.resolve("帮我做一张各城市房价对比表。"))
    r.check("提示词带语境策略段落", "## 语境策略" in payload["prompt"])
    r.check("提示词写明降档原因", "表格" in payload["prompt"])
    r.check("提示词仍然带安全段落", "安全边界" in payload["prompt"])

    crisis = _context.resolve("我不想活了")
    payload = compose_prompt.compose([("S09", 1)], None, "standard", None, crisis)
    r.check("危机时提示词不含风格全文",
            "## 主风格全文" not in payload["prompt"], payload["prompt"][:120])
    r.check("危机时提示词要求关闭风格",
            "本轮完全关闭风格" in payload["prompt"])
    r.check("危机时提示词仍给出求助渠道", "120" in payload["prompt"]
            and "12356" in payload["prompt"])

    # -- 宿主适配层：旧调用方式不变 --------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "user-config.json"
        history_path = tmp_path / "tone-history.json"
        write_config(config_path)

        # 最小参数调用（合同测试）
        host = ToneHost(config_path=config_path, history_path=history_path, seed=7)
        host.begin_session()
        turn = host.next_turn("你好")
        for field in ("active", "system_suffix", "style", "members", "density_range",
                      "notes"):
            r.check(f"next_turn 仍返回 {field}", field in turn)
        r.check("旧调用不需要新参数", turn["active"] is True)
        r.check("普通对话不降档", turn["density"] == "standard", turn["density"])

        # 代码任务自动降档
        host = ToneHost(config_path=config_path, history_path=history_path, seed=7)
        host.begin_session()
        turn = host.next_turn("帮我看看这段 Python 代码报了个 KeyError\n```python\nx=1\n```")
        r.check("代码任务自动降到轻档", turn["density"] == "light", turn["density"])
        r.check("代码任务给出 reason code", turn["context"]["reason_code"] == "code")
        r.check("代码任务的提示词带语境段落",
                "## 语境策略" in turn["system_suffix"])

        # 危机：完全关闭风格，且不抽样
        crisis_history = tmp_path / "crisis-history.json"
        host = ToneHost(config_path=config_path, history_path=crisis_history, seed=7)
        host.begin_session()
        turn = host.next_turn("我不想活了，活着没意思。")
        r.check("危机时 active=False", turn["active"] is False)
        r.check("危机时不注入任何提示词", turn["system_suffix"] == "")
        r.check("危机时不给风格", turn["style"] is None)
        r.check("危机时不写历史", not crisis_history.exists())
        r.check("危机时状态不前进", host.get_state()["turn"] == 0)

        # 显式场景覆盖
        host = ToneHost(config_path=config_path, history_path=history_path, seed=7)
        host.begin_session()
        turn = host.next_turn("普通闲聊", context={"scene": "high_risk"})
        r.check("显式场景影响密度", turn["density"] == "light", turn["density"])
        r.check("显式场景写入结果", turn["context"]["source"] == "explicit")

        # scene_adapt=false 时不做自动降档
        write_config(config_path, scene_adapt=False)
        host = ToneHost(config_path=config_path, history_path=history_path, seed=7)
        host.begin_session()
        turn = host.next_turn("帮我做一张各城市房价对比表。")
        r.check("scene_adapt=false 时不自动降档", turn["density"] == "standard",
                turn["density"])
        write_config(config_path)

        # 暂停仍然优先（暂停 ≠ 危机）
        write_config(config_path, paused=True)
        host = ToneHost(config_path=config_path, history_path=history_path, seed=7)
        host.begin_session()
        turn = host.next_turn("你好")
        r.check("暂停时 active=False", turn["active"] is False)
        r.check("暂停时给出说明", any("暂停" in note for note in turn["notes"]))
        write_config(config_path)

    # -- 四种模式在语境策略下仍然可用 ------------------------------------------
    for mode in ("single", "blend", "rotate", "blend_random"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "user-config.json"
            history_path = tmp_path / "tone-history.json"
            write_config(config_path, mode=mode,
                         styles=[{"id": "S09", "weight": 3}, {"id": "S04", "weight": 2}])
            host = ToneHost(config_path=config_path, history_path=history_path, seed=7)
            host.begin_session()
            turn = host.next_turn("帮我看看这段代码\n```python\nx=1\n```")
            r.check(f"{mode} 模式在语境策略下仍可运行",
                    turn["active"] is True and turn["style"] is not None)

    # -- 融合冲突的确定性解决：安全 > 主风格 > 副风格 ----------------------------
    catalog_data, index = _core.load_catalog()
    for pair in catalog_data.get("conflict_pairs", []):
        payload = compose_prompt.compose([(pair[0], 4), (pair[1], 2)], [4, 2],
                                          "standard", None)
        r.check(f"冲突风格 {pair[0]}+{pair[1]} 的提示词仍带安全段落",
                "安全边界" in payload["prompt"])
        r.check(f"冲突风格 {pair[0]}+{pair[1]} 标记出冲突",
                any(item["main"] == pair[0] and item["accent"] == pair[1]
                    for item in payload["conflicts"]), str(payload["conflicts"]))
        r.check(f"冲突风格 {pair[0]}+{pair[1]} 采用反差融合的确定性说明",
                "反差融合" in payload["prompt"])

    # -- MCP 工具的语境参数（真实子进程） ---------------------------------------
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        mcp_cfg = Path(tmp) / "user-config.json"
        write_config(mcp_cfg)

        def mcp_call(arguments):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "mcp" / "server.py"),
                 "--config", str(mcp_cfg)],
                input=json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "get_style_prompt", "arguments": arguments},
                }) + "\n",
                capture_output=True, text=True, timeout=60)
            return json.loads(proc.stdout.strip())

        response = mcp_call({"style_id": "S09", "context": {"scene": "code"}})
        payload = json.loads(response["result"]["content"][0]["text"])
        r.check("MCP get_style_prompt 支持 context 参数",
                payload["density"] == "light", payload["density"])
        r.check("MCP 语境写进提示词", "## 语境策略" in payload["prompt"])
        r.check("MCP 返回语境决策", payload.get("context", {}).get("reason_code") == "code")

        response = mcp_call({"style_id": "S09"})
        payload = json.loads(response["result"]["content"][0]["text"])
        r.check("MCP 不传 context 时保持原行为",
                payload["density"] == "standard" and "## 语境策略" not in payload["prompt"])

        response = mcp_call({"style_id": "S09", "context": {"scene": "crisis"}})
        r.check("MCP 拒绝把 crisis 作为显式场景",
                response.get("error", {}).get("code") == -32602,
                json.dumps(response, ensure_ascii=False)[:160])

        response = mcp_call({"style_id": "S09", "context": {"scene": "不存在的场景"}})
        r.check("MCP 拒绝未知场景",
                response.get("error", {}).get("code") == -32602,
                json.dumps(response, ensure_ascii=False)[:160])

        response = mcp_call({"style_id": "S09", "context": {"未知字段": 1}})
        r.check("MCP 拒绝 context 里的未知字段",
                response.get("error", {}).get("code") == -32602,
                json.dumps(response, ensure_ascii=False)[:160])

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
