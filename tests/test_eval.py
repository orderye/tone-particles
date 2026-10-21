#!/usr/bin/env python3
"""评测体系的测试（纯标准库）。

重点验证「状态语义」这件事：
- 通过 / 未达标 / 未评测 / 被阻塞四种状态必须分得清
- 「未评测」不能被渲染成通过，也不能被算成不达标
- 后端出错要记成「被阻塞」，不能记成「目标回复失败」
- 报告的 Markdown 与 JSON 必须一致

运行：python3 tests/test_eval.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import ROOT, Runner  # noqa: E402

EVAL_ROOT = ROOT / "eval"
sys.path.insert(0, str(EVAL_ROOT))

import report as reporter  # noqa: E402
import validate_cases  # noqa: E402
from judge import anchors, blind  # noqa: E402
from judge.common import (  # noqa: E402
    STATUS_BLOCKED,
    STATUS_FAILED,
    STATUS_NOT_EVALUATED,
    STATUS_PASSED,
    blocked_metric,
    metric,
    skipped_metric,
)


class BrokenBackend:
    """评审通道出错的假后端：每次调用都抛错。"""

    name = "broken"

    def available(self):
        return True, "测试用：总是出错"

    def metadata(self):
        return {"后端": self.name, "模型": "unknown"}

    def generate(self, system, user):
        raise SystemExit("模型接口返回 503")

    def judge(self, rubric, payload):
        raise SystemExit("模型接口返回 503")


class SilentBackend:
    """评审通道通、但模型没给结论的假后端。"""

    name = "silent"

    def available(self):
        return True, "测试用：不给结论"

    def metadata(self):
        return {"后端": self.name, "模型": "unknown"}

    def generate(self, system, user):
        return ""

    def judge(self, rubric, payload):
        return {}


class FakeBackend:
    """按用例 id 给出固定结论的假后端。"""

    name = "fake"

    def __init__(self, choices):
        self.choices = choices

    def available(self):
        return True, "测试用：固定结论"

    def metadata(self):
        return {"后端": self.name, "模型": "unknown"}

    def generate(self, system, user):
        return "去语气后的正文"

    def judge(self, rubric, payload):
        case_id = payload.get("case_id")
        if case_id not in self.choices:
            return {}
        return {"choice": self.choices[case_id]}


def main() -> int:
    r = Runner("评测体系")

    # -- 状态语义 ------------------------------------------------------------
    r.check("passed=True → passed",
            metric("m", "t", "v", True)["status"] == STATUS_PASSED)
    r.check("passed=False → failed",
            metric("m", "t", "v", False)["status"] == STATUS_FAILED)
    r.check("skipped=True → not_evaluated",
            metric("m", "t", "v", None, skipped=True)["status"] == STATUS_NOT_EVALUATED)
    r.check("skipped_metric → not_evaluated",
            skipped_metric("m", "t", "原因")["status"] == STATUS_NOT_EVALUATED)
    r.check("blocked_metric → blocked",
            blocked_metric("m", "t", "原因")["status"] == STATUS_BLOCKED)
    r.check("状态字段与旧字段并存（passed=True）",
            metric("m", "t", "v", True)["passed"] is True
            and metric("m", "t", "v", True)["skipped"] is False)

    # -- 报告渲染区分四种状态 -------------------------------------------------
    metrics = [
        metric("甲", "线", "v", True, counts={"passed": 1, "failed": 0,
                                          "not_evaluated": 0, "blocked": 0, "denominator": 1}),
        metric("乙", "线", "v", False, failures=[{"case_id": "c1", "reason": "坏"}]),
        skipped_metric("丙", "线", "没后端",
                       notes=[{"case_id": "c2", "reason": "缺回复，未计入"}]),
        blocked_metric("丁", "线", "通道挂了"),
    ]
    text = reporter.render(metrics, {"版本": "0.0.0"})
    r.check("报告渲染「通过」", "✅ 通过" in text)
    r.check("报告渲染「未达标」", "❌ 未达标" in text)
    r.check("报告渲染「未评测」", "⏭️ 未评测" in text)
    r.check("报告渲染「被阻塞」", "⛔ 被阻塞" in text)
    r.check("未评测与未达标分栏",
            "未通过明细" in text and "未计入明细" in text and "被阻塞明细" in text)
    r.check("总览给出四种状态的计数",
            "通过 1 项" in text and "未达标 1 项" in text
            and "未评测 1 项" in text and "被阻塞 1 项" in text)

    # -- 后端出错 → 被阻塞，不是未达标 ------------------------------------------
    cases = {"cases": [{"id": "b-01", "style": "S09", "prompt": 0, "min_chars": 150}],
             "pool": ["问题"]}
    result = blind.judge({"b-01": "回复"}, cases, BrokenBackend())
    r.check("后端出错时指标为被阻塞", result["status"] == STATUS_BLOCKED, str(result["status"]))
    r.check("后端出错时不算未达标", not result["failures"], str(result["failures"]))
    r.check("后端出错时记下阻塞条目", len(result["blocked"]) == 1, str(result["blocked"]))

    # -- 后端通了但没给结论 → 未评测 -------------------------------------------
    result = blind.judge({"b-01": "回复"}, cases, SilentBackend())
    r.check("评审没作答时指标为未评测",
            result["status"] == STATUS_NOT_EVALUATED, str(result["status"]))
    r.check("评审没作答时不算未达标", not result["failures"], str(result["failures"]))
    r.check("评审没作答时记在未计入明细里", len(result["notes"]) == 1, str(result["notes"]))

    # -- 盲测泄漏 --------------------------------------------------------------
    leaked = {"cases": [{"id": "b-02", "style": "S09", "prompt": 0, "min_chars": 150}],
              "pool": ["问题"]}
    result = blind.judge({"b-02": "我这是傲娇风格哦"}, leaked, FakeBackend({}))
    r.check("盲测泄漏被判为失败",
            result["status"] == STATUS_FAILED and len(result["failures"]) == 1,
            str(result["failures"]))

    # -- 语义锚点 --------------------------------------------------------------
    anchor_cases = {"cases": [
        {"id": "a-01", "style": "S09",
         "anchors": ["120", "2024-05-01", "/dev/null", "https://example.com/docs"]},
        {"id": "a-02", "style": "S09", "forbidden_anchors": ["911"]},
    ]}
    result = anchors.judge({
        "a-01": "请拨打 120，日期 2024-05-01，重定向到 /dev/null，"
                "文档见 https://example.com/docs。",
        "a-02": "这条回复里没有那个号码。",
    }, anchor_cases)
    r.check("锚点全部保留时通过", result["status"] == STATUS_PASSED, str(result["failures"]))
    r.check("锚点计数正确", result["counts"]["denominator"] == 5, str(result["counts"]))

    result = anchors.judge({
        "a-01": "请拨打 1200，日期 2024-05-01，重定向到 /dev/null。",
        "a-02": "这条回复里有 911。",
    }, anchor_cases)
    r.check("数字边界：1200 不算命中 120",
            any("120" in item["reason"] for item in result["failures"]),
            str(result["failures"]))
    r.check("缺失的 URL 被判失败",
            any("https://example.com/docs" in item["reason"]
                for item in result["failures"]), str(result["failures"]))
    r.check("不该出现的片段被判失败",
            any("911" in item["reason"] for item in result["failures"]),
            str(result["failures"]))

    # -- 用例结构校验 ----------------------------------------------------------
    problems = validate_cases.validate_all()
    r.check("真实用例集结构完好", not problems, str(problems))

    with tempfile.TemporaryDirectory() as tmp:
        broken_dir = Path(tmp)
        (broken_dir / "chats.json").write_text(json.dumps({
            "version": 1,
            "cases": [
                {"id": "x-01", "style": "S99", "scene": "normal", "min_chars": 150,
                 "user_input": "…"},
                {"id": "x-01", "style": "S09", "scene": "unknown_scene",
                 "min_chars": 0, "user_input": "…"},
            ],
        }), encoding="utf-8")
        (broken_dir / "blind.json").write_text(json.dumps({
            "version": 1, "pool": ["题"],
            "cases": [{"id": "x-01", "style": "S09", "prompt": 9, "min_chars": 150}],
        }), encoding="utf-8")
        for name in ("fusion", "redteam", "scenes"):
            (broken_dir / f"{name}.json").write_text(json.dumps(
                {"version": 1, "cases": []}), encoding="utf-8")
        problems = validate_cases.validate_all(broken_dir)
        joined = " ".join(problems)
        r.check("校验能发现非法风格 id", "S99" in joined, joined)
        r.check("校验能发现重复 id", "重复" in joined, joined)
        r.check("校验能发现非法 scene", "unknown_scene" in joined, joined)
        r.check("校验能发现非法 min_chars", "min_chars" in joined, joined)
        r.check("校验能发现题池索引越界", "越界" in joined, joined)
        r.check("校验能发现空用例集", "非空列表" in joined, joined)

    # -- 命令行：退出码与报告一致性 ---------------------------------------------
    def run_eval(extra=()):
        return subprocess.run(
            [sys.executable, str(EVAL_ROOT / "run.py"), *extra],
            capture_output=True, text=True, timeout=300)

    proc = run_eval()
    r.check("默认运行退出码为 0", proc.returncode == 0, proc.stderr[-300:])
    r.check("默认报告里写明未评测项",
            "未评测" in proc.stdout, proc.stdout[-300:])

    proc = run_eval(["--strict"])
    r.check("严格模式退出码为 2（模型类指标未评测）", proc.returncode == 2,
            f"exit={proc.returncode}")
    r.check("严格模式报告里点名未评测的模型类指标",
            "风格盲测" in proc.stdout and "未评测" in proc.stdout)

    proc = run_eval(["--json"])
    payload = json.loads(proc.stdout)
    r.check("--json 输出可解析", "metrics" in payload and "meta" in payload)
    r.check("--json 里每项指标都有状态",
            all("status" in item for item in payload["metrics"]))

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.md"
        run_eval(["--out", str(out)])
        r.check("报告写出 .md", out.exists())
        r.check("报告写出 .json", out.with_suffix(".json").exists())
        md_text = out.read_text(encoding="utf-8")
        json_payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
        proc = run_eval(["--json"])
        stdout_payload = json.loads(proc.stdout)
        r.check("--out 写出的 JSON 与 --json 输出的指标一致",
                json_payload["metrics"] == stdout_payload["metrics"])
        r.check("--out 写出的 JSON 与 --json 输出的元信息一致",
                json_payload["meta"]["评测数据哈希"]
                == stdout_payload["meta"]["评测数据哈希"])
        r.check("Markdown 与 JSON 的指标数一致",
                md_text.count("| PRD 通过线 |") == 1
                and all(item["metric"] in md_text for item in json_payload["metrics"]))
        r.check("报告带 schema 版本", "报告 schema 版本" in md_text)

    # -- 确定性指标可复现 ------------------------------------------------------
    first = run_eval(["--json"])
    second = run_eval(["--json"])
    a = json.loads(first.stdout)["metrics"]
    b = json.loads(second.stdout)["metrics"]
    deterministic = [item["metric"] for item in a if not item.get("requires_model")]
    r.check("确定性指标两次运行结果一致",
            [item["value"] for item in a if item["metric"] in deterministic]
            == [item["value"] for item in b if item["metric"] in deterministic],
            str([item["value"] for item in a if item["metric"] in deterministic]))

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
