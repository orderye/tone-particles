"""人工后端：在终端里按提示录入评审结论。

用途是没有配置任何模型接口时，仍能把评测链路走通：回复先手工放进
fixtures/responses/（或由一个可用的模型后端生成），评审阶段由人工按提示选择。
录入结果会存到 fixtures/judgments/，之后可用 fixture 后端离线复跑。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Backend

DEFAULT_RESPONSES = Path(__file__).resolve().parent.parent / "fixtures" / "responses"
DEFAULT_JUDGMENTS = Path(__file__).resolve().parent.parent / "fixtures" / "judgments"


class ManualBackend(Backend):
    name = "manual"
    can_generate = False

    def __init__(self, responses_dir=None, judgments_dir=None):
        self.responses_dir = Path(responses_dir) if responses_dir else DEFAULT_RESPONSES
        self.judgments_dir = Path(judgments_dir) if judgments_dir else DEFAULT_JUDGMENTS

    def available(self):
        return True, "人工录入模式"

    def metadata(self) -> dict:
        return {
            "后端": self.name,
            "模型": "人工评审",
            "采样参数": "不适用",
            "档案目录": str(self.judgments_dir),
        }

    def generate(self, system: str, user: str) -> str:
        raise RuntimeError(
            "manual 后端不支持生成回复；请把回复手工放进 fixtures/responses/，"
            "或用 chat_completions / messages_api 生成。")

    def judge(self, rubric: str, payload: dict) -> dict:
        case_id = payload.get("case_id")
        if not case_id:
            return {}
        path = self.judgments_dir / f"{case_id}.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)

        options = payload.get("options")
        if not options:
            return {}

        print(f"\n=== 人工评审 {case_id} ===")
        print(payload.get("display", ""))
        for index, option in enumerate(options, start=1):
            print(f"  {index}. {option}")
        while True:
            try:
                raw = input("请选择（序号，直接回车跳过）：").strip()
            except EOFError:
                # 非交互环境（管道/CI）里不要卡住整批评测
                print("（无交互输入，跳过本条）")
                return {}
            if not raw:
                return {}
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                break
            print("  输入无效，请输入列表中的序号。")

        result = {"choice": options[int(raw) - 1]}
        self.judgments_dir.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        return result
