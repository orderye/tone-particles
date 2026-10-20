"""模型后端接口。

判分器与后端之间只有两个方法：
- generate(system, user) -> str：生成一条回复。
- judge(rubric, payload) -> dict：按评分标准评审，返回结构化结果。

没有配置后端时，依赖模型的三项指标（盲测、内容保真、融合识别）标记为
skipped，其余确定性指标照常产出。
"""

from __future__ import annotations

import json
import re

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


class Backend:
    name = "base"
    # 是否能真的生成回复（档案/人工后端不能；run.py --generate 会据此提前报错）
    can_generate = False

    def available(self):
        """返回 (是否可用, 原因)。不可用时原因会写进报告。"""
        return False, "未配置后端"

    def generate(self, system: str, user: str) -> str:
        raise NotImplementedError

    def judge(self, rubric: str, payload: dict) -> dict:
        raise NotImplementedError

    # -- 共用工具 ---------------------------------------------------------

    @staticmethod
    def parse_json_reply(text: str) -> dict:
        """从回复里抠出 JSON 对象。模型常把 JSON 包在 ```json 围栏里。"""
        if not text:
            return {}
        candidate = text.strip()
        match = JSON_FENCE_RE.search(candidate)
        if match:
            candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        # 退而求其次：抓第一个平衡的 {...}
        start = candidate.find("{")
        if start == -1:
            return {}
        depth = 0
        for index in range(start, len(candidate)):
            if candidate[index] == "{":
                depth += 1
            elif candidate[index] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[start:index + 1])
                    except json.JSONDecodeError:
                        return {}
        return {}


def get_backend(name: str, **options) -> Backend:
    """按名字构造后端。未知名字会抛错，调用方负责降级为 skipped。"""
    if name in ("none", ""):
        return Backend()
    if name == "fixture":
        from .fixture import FixtureBackend
        return FixtureBackend(**options)
    if name == "chat_completions":
        from .chat_completions import ChatCompletionsBackend
        return ChatCompletionsBackend(**options)
    if name == "messages_api":
        from .messages_api import MessagesApiBackend
        return MessagesApiBackend(**options)
    if name == "manual":
        from .manual import ManualBackend
        return ManualBackend(**options)
    raise SystemExit(
        f"未知后端：{name}。可用：none / fixture / chat_completions / messages_api / manual"
    )
