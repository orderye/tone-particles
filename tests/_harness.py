"""极简测试脚手架：不引 pytest，纯标准库。

用法：

    from _harness import ROOT, Runner

    def main() -> int:
        r = Runner("某个模块")
        r.check("断言名", condition, "失败的补充说明")
        r.raises("非法输入要报错", lambda: module.do_bad(), contains="关键词")
        return r.finish()

    if __name__ == "__main__":
        sys.exit(main())
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class Runner:
    def __init__(self, name: str):
        self.name = name
        self.passed: list = []
        self.failed: list = []

    def check(self, name: str, condition, detail: str = "") -> None:
        if condition:
            self.passed.append(name)
        else:
            self.failed.append(f"{name}{'：' + detail if detail else ''}")

    def raises(self, name: str, func, *, contains: str | None = None) -> None:
        """断言 func() 抛出 SystemExit，且消息包含 contains（可选）。"""
        try:
            func()
        except SystemExit as exc:
            message = str(exc)
            if contains and contains not in message:
                self.failed.append(f"{name}：报错未包含 {contains!r}（实际 {message!r}）")
            else:
                self.passed.append(name)
        except Exception as exc:  # noqa: BLE001
            self.failed.append(f"{name}：抛出 {type(exc).__name__} 而非 SystemExit：{exc}")
        else:
            self.failed.append(f"{name}：没有抛出 SystemExit")

    def finish(self) -> int:
        print(f"[{self.name}] 通过 {len(self.passed)} 项，失败 {len(self.failed)} 项")
        for item in self.failed:
            print(f"  ✗ {item}")
        return 1 if self.failed else 0
