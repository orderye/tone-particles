"""判分器集合。

每个 judge 函数签名统一为 judge(responses, cases, **kwargs) -> dict，
返回的 dict 至少包含 metric / threshold / value / passed / skipped / status /
detail / failures / notes / blocked / counts。
"""

from . import anchors, blind, density, fidelity, fusion, kaomoji, random_mode, redteam, rules, scene

__all__ = [
    "anchors",
    "blind",
    "density",
    "fidelity",
    "fusion",
    "kaomoji",
    "random_mode",
    "redteam",
    "rules",
    "scene",
]
