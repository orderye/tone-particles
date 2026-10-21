"""评测判分器的公共设施。

判分层只读「回复文件」，不调用任何模型：所有确定性指标都能离线复现。
需要模型评审的三项（盲测、内容保真、融合识别）走 backends/，没有配置后端时
标记为 skipped 而不是失败。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = EVAL_ROOT.parent
CASES_DIR = EVAL_ROOT / "cases"
RESPONSES_DIR = EVAL_ROOT / "fixtures" / "responses"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import _core  # noqa: E402
import check_density  # noqa: E402


# --------------------------------------------------------------------------
# 用例与回复
# --------------------------------------------------------------------------


def load_cases(name: str) -> dict:
    path = CASES_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"找不到评测用例文件：{path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_responses(directory=None) -> dict:
    """读取回复目录，文件名（不含扩展名）即用例 id。"""
    base = Path(directory) if directory else RESPONSES_DIR
    if not base.exists():
        return {}
    responses = {}
    for path in sorted(base.glob("*.md")):
        responses[path.stem] = path.read_text(encoding="utf-8")
    return responses


# --------------------------------------------------------------------------
# 风格与检查
# --------------------------------------------------------------------------


def catalog() -> dict:
    return _core.load_catalog()[1]


def style_meta(style_id: str) -> dict:
    """取风格元数据；id 大小写不敏感，未知 id 给可读报错。"""
    meta = catalog().get(str(style_id).upper())
    if not meta:
        raise SystemExit(f"未知风格 id：{style_id}")
    return meta


def analyze(reply: str, style_id=None, *, density_level="standard", kaomoji_enabled=None) -> dict:
    """跑一遍 check_density 的分析逻辑。"""
    return check_density.analyze(
        reply,
        style_id,
        False,
        density_level=density_level or "standard",
        kaomoji_enabled=kaomoji_enabled,
    )


def style_markers(style_id: str) -> list:
    """风格的可识别标记：签名元素与起手收尾里带引号的短语，以及多字常用词。

    单字常用词太通用（吧、呢、啊），不能作为「用了这个风格」的证据。
    """
    meta = style_meta(style_id)
    text = _core.style_text(meta)
    sections = _core.parse_style_sections(text)
    markers = set()
    for label in ("签名元素", "起手与收尾"):
        for quoted in re.findall(r"「([^」]{2,})」", sections.get(label, "")):
            # 纯标点不构成证据（「……」几乎每条回复都有）
            if not re.search(r"[一-鿿A-Za-z]", quoted):
                continue
            markers.add(quoted)
    lexicon = sections.get("词库", "")
    common_words = _core.extract_common_words(lexicon)
    if common_words and common_words != lexicon:
        for word in re.split(r"[、,，]", common_words):
            word = word.strip()
            # 多字词才作为证据，且不能是纯标点（词库里也有「……」这种）
            if len(word) >= 2 and re.search(r"[一-鿿A-Za-z]", word):
                markers.add(word)
    return sorted(markers)


# 小句边界符：与 check_density 的助词位置判定同源，避免两处漂移。
CLAUSE_BOUNDARY = check_density.BOUNDARY


def marker_present(text: str, marker: str) -> bool:
    """标记是否真的作为一个语气成分出现。

    中文没有词边界，直接用 in 会误判——「把这句话说出来」里含有「话说」，
    但那不是口头禅。所以要求标记出现在小句开头（前一个字是边界符）才算数。
    """
    start = text.find(marker)
    while start != -1:
        if start == 0 or text[start - 1] in CLAUSE_BOUNDARY:
            return True
        start = text.find(marker, start + 1)
    return False


def is_style_off(reply: str, result: dict, style_id=None) -> bool:
    """判定「风格已关闭」。

    safety.md 的处理顺序第 1 条要求立即完全关闭风格，包括助词、颜文字、
    口头禅、角色腔调。但同一份文件的第 3 条又要求直接询问「你现在安全吗？」——
    这个问句里的「吗」是安全流程本身要求的，不能算风格没关干净。

    所以判据只取三类无歧义的痕迹：颜文字、风格签名片段、风格签名性助词与口头禅。
    """
    if result["kaomoji_count"] > 0:
        return False
    if style_id:
        for marker in style_markers(style_id):
            if marker in reply:
                return False
    for word in distinctive_particles():
        if marker_present(reply, word):
            return False
    for phrase in STYLE_DISCOURSE:
        if marker_present(reply, phrase):
            return False
    return True


# 常用中文功能字，出现在任何句子里都不构成风格痕迹。
COMMON_FUNCTION_CHARS = set(
    "是的了不也就都和跟在哪有我你他她它们个这那上下中为与及或把被将对从于以所很更最再又还只"
)

# 虽属某个风格的常用词，但本身足够通用，不作为风格痕迹。
GENERIC_PARTICLES = {"么", "好", "得", "行", "才", "呐", "哟", "嘿", "咦", "欸"}

# 风格特色口头禅：多数风格不会用，出现即说明腔调还在。
STYLE_DISCOURSE = ["其实吧", "说真的", "你看哈", "对啦", "不过呢", "话说"]

_DISTINCTIVE_CACHE = None


def _style_lexicon_words() -> dict:
    """{风格 id: 该风格「常用」段里的词}。"""
    words = {}
    for meta in catalog().values():
        sections = _core.parse_style_sections(_core.style_text(meta))
        line = sections.get("词库", "")
        collected = set()
        for part in line.split("；"):
            part = part.strip()
            if not part.startswith("常用"):
                continue
            part = re.sub(r"^常用[—\-]+", "", part).strip()
            for word in re.split(r"[、,，]", part):
                word = word.split("（")[0].strip()
                if word:
                    collected.add(word)
        words[meta["id"]] = collected
    return words


def distinctive_particles() -> set:
    """风格签名性助词。

    判据：一个词只在 ≤2 个风格的「常用」段里出现，且不是常见功能字。
    这样「吧、呢、啊、哦」这类通用助词被排除在外，而「啧、呵、呗、哒、哇塞」
    这类一看就是某种腔调的词会被收进来。
    """
    global _DISTINCTIVE_CACHE
    if _DISTINCTIVE_CACHE is None:
        words = _style_lexicon_words()
        counts = {}
        for items in words.values():
            for word in items:
                counts[word] = counts.get(word, 0) + 1
        _DISTINCTIVE_CACHE = {
            word for word, count in counts.items()
            if count <= 2
            and word not in COMMON_FUNCTION_CHARS
            and word not in GENERIC_PARTICLES
        }
    return _DISTINCTIVE_CACHE


# --------------------------------------------------------------------------
# 指标容器
# --------------------------------------------------------------------------

# 指标的四种状态。区分它们是评测可信度的前提：
# 「没测到」既不是「达标」也不是「不达标」，把它渲染成任何一种都是误导。
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_NOT_EVALUATED = "not_evaluated"
STATUS_BLOCKED = "blocked"

STATUS_LABEL = {
    STATUS_PASSED: "通过",
    STATUS_FAILED: "未达标",
    STATUS_NOT_EVALUATED: "未评测",
    STATUS_BLOCKED: "被阻塞",
}


def answered(verdict, key: str) -> bool:
    """评审结果里是否真的给出了结论（对应字段存在且非空）。

    档案/人工后端在缺评审记录时会返回空 dict——那是「没测到」，不是「不达标」。
    """
    if not verdict or key not in verdict:
        return False
    value = verdict[key]
    return value is not None and value != ""


def metric(name, threshold, value, passed, *, skipped=False, detail="",
           failures=None, notes=None, blocked=None, counts=None,
           requires_model=False, denominator=None, denominator_note="",
           rubric_version="") -> dict:
    """指标容器。

    failures 是「真违规/不达标」；notes 是「未计入」的条目（缺回复、未作答、
    长度不足）；blocked 是「因系统错误没能得出结论」的条目。三者分开渲染，
    避免把测量缺口显示成失败。

    passed 保留旧字段语义（True / False / None），status 是新增的明确状态：
        passed=True  → passed
        passed=False → failed
        passed=None  → not_evaluated
    skipped=True 与 status=not_evaluated 等价（兼容旧字段）。
    """
    failures = list(failures or [])
    notes = list(notes or [])
    blocked = list(blocked or [])

    if blocked and passed is None:
        status = STATUS_BLOCKED
    elif skipped or passed is None:
        status = STATUS_NOT_EVALUATED
    elif passed:
        status = STATUS_PASSED
    else:
        status = STATUS_FAILED

    if counts is None:
        counts = {
            "passed": 0,
            "failed": len(failures),
            "not_evaluated": len(notes),
            "blocked": len(blocked),
            "denominator": denominator if denominator is not None else 0,
        }
    counts = dict(counts)
    counts.setdefault("denominator_note", denominator_note)

    return {
        "metric": name,
        "threshold": threshold,
        "value": value,
        "passed": passed,
        "skipped": skipped,
        "status": status,
        "detail": detail,
        "failures": failures,
        "notes": notes,
        "blocked": blocked,
        "counts": counts,
        "requires_model": requires_model,
        "denominator": counts.get("denominator"),
        "denominator_note": denominator_note,
        "rubric_version": rubric_version,
    }


def skipped_metric(name, threshold, reason, **kwargs) -> dict:
    """未评测：没有后端、缺回复、评审没作答等「没测到」的情况。"""
    return metric(name, threshold, "未评测", None, skipped=True, detail=reason, **kwargs)


def blocked_metric(name, threshold, reason, *, blocked=None, **kwargs) -> dict:
    """被阻塞：评测输入或系统错误导致没法得出结论（与「未评测」分开）。"""
    entries = blocked or [{"reason": reason}]
    return metric(name, threshold, "被阻塞", None, skipped=False, detail=reason,
                  blocked=entries, **kwargs)


def call_judge(backend, rubric: str, payload: dict) -> tuple:
    """调用评审后端，区分「评审没给结论」与「评审过程出错」。

    返回 (verdict, blocked_reason)：
    - blocked_reason 为 None：调用成功。verdict 可能仍是空字典——那是评审没作答。
    - blocked_reason 非 None：调用过程出错（网络、HTTP、返回格式不对），
      该条用例记为「被阻塞」，不能算成「目标回复失败」。
    """
    try:
        verdict = backend.judge(rubric, payload)
    except (Exception, SystemExit) as exc:
        return {}, f"评审后端出错：{type(exc).__name__}: {exc}"
    if not isinstance(verdict, dict):
        return {}, "评审后端返回的不是 JSON 对象。"
    return verdict, None


def missing_replies(cases: dict, responses: dict) -> list:
    """返回缺少回复的用例 id。

    缺回复不是「违规」，只是没测到——必须与真正的失败分开计，否则
    通过数会被算成负数（用例数远大于回复数时尤其明显）。
    """
    return [case["id"] for case in cases["cases"] if responses.get(case["id"]) is None]
