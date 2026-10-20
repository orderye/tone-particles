"""档案后端：从本地文件读取生成结果与评审结果。

用途有两个：
- 没有模型可用时，用已存档的回复跑确定性指标。
- 把人工盲测录入的结果喂给判分器（judge 读 <judgments_dir>/<case_id>.json）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Backend

DEFAULT_RESPONSES = Path(__file__).resolve().parent.parent / "fixtures" / "responses"
DEFAULT_JUDGMENTS = Path(__file__).resolve().parent.parent / "fixtures" / "judgments"


class FixtureBackend(Backend):
    name = "fixture"

    def __init__(self, responses_dir=None, judgments_dir=None):
        self.responses_dir = Path(responses_dir) if responses_dir else DEFAULT_RESPONSES
        self.judgments_dir = Path(judgments_dir) if judgments_dir else DEFAULT_JUDGMENTS

    def available(self):
        if not self.responses_dir.exists():
            return False, f"档案目录不存在：{self.responses_dir}"
        return True, f"使用档案目录 {self.responses_dir}"

    def generate(self, system: str, user: str) -> str:
        # 生成阶段由 run.py 直接读档案，不经过这里
        return ""

    def judge(self, rubric: str, payload: dict) -> dict:
        case_id = payload.get("case_id")
        if not case_id:
            return {}
        path = self.judgments_dir / f"{case_id}.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
