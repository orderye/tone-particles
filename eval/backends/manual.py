"""人工后端：在终端里粘贴生成结果、勾选评审结论。

用途是没有配置任何模型接口时，仍能把整条评测链路走通——生成阶段粘贴回复，
评审阶段按提示选择选项。录入结果会存到 fixtures 目录，下次可当档案复用。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Backend

DEFAULT_RESPONSES = Path(__file__).resolve().parent.parent / "fixtures" / "responses"
DEFAULT_JUDGMENTS = Path(__file__).resolve().parent.parent / "fixtures" / "judgments"


class ManualBackend(Backend):
    name = "manual"

    def __init__(self, responses_dir=None, judgments_dir=None):
        self.responses_dir = Path(responses_dir) if responses_dir else DEFAULT_RESPONSES
        self.judgments_dir = Path(judgments_dir) if judgments_dir else DEFAULT_JUDGMENTS

    def available(self):
        return True, "人工录入模式"

    def generate(self, system: str, user: str) -> str:
        return ""

    def record_response(self, case_id: str, text: str) -> None:
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        (self.responses_dir / f"{case_id}.md").write_text(text, encoding="utf-8")

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
            raw = input("请选择（序号，直接回车跳过）：").strip()
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
