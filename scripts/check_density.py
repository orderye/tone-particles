#!/usr/bin/env python3
"""检测语气助词密度与硬规则。

用法：
    python3 scripts/check_density.py reply.txt --style S09
    cat reply.txt | python3 scripts/check_density.py --style S02 --json
    python3 scripts/check_density.py reply.txt --strict

说明：
- 密度 = 主助词次数 / 正文汉字数 × 100；结构性「的 / 了」单独统计，不计入密度。
- 位置规则：句末类只在分句末尾计数；句首类只在分句开头计数；固定短语任意位置计数。
- 规则检查：每小句 ≤ 1 个主助词、不堆叠、代码 / 表格 / 链接内无助词、禁用词。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
PARTICLES_PATH = SKILL_ROOT / "config" / "particles.json"
STYLES_PATH = SKILL_ROOT / "config" / "styles.json"

CJK_RE = re.compile(r"[一-鿿]")
CLAUSE_SPLIT_RE = re.compile(r"[^。！？!?；;，,、：:\n…～~]+")
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
BOUNDARY = set("。！？!?；;，,、：:…—～~（）()【】[]「」『』\"'“”‘’ \t\n\r|")

# 常见词里的「伪助词」，避免误计
EXCEPTION_WORDS = [
    "酒吧", "网吧", "吧台", "吗啡", "哈欠", "哈佛", "哈尔滨", "近乎", "几乎",
    "在乎", "似乎", "呼吸", "呼吁", "呼气", "呼声", "一切", "切换", "切实",
    "罢工", "呢喃", "哼歌", "呜咽", "咕咚",
]

KAOMOJI_CHARS = set("≧≦▽ωᴗ✿◕‿¬¯︶︿皿ε°⊙дﾟヮᗜ๑ゞノヽﾉ٩ง✧☆★")
KAOMOJI_RE = re.compile(r"[\(（][^\)）\n]{1,24}[\)）]")
ASCII_KAOMOJI_RE = re.compile(r"\^_\^|:\)|:D|T_T|;-;|>_<")

# 位置策略
FINAL_OVERRIDES = {"耶"}
INITIAL_OVERRIDES = {"呼"}
ANYWHERE_OVERRIDES = set()


def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"找不到文件：{path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"不是合法 JSON：{path}（{exc}）")


def build_lexicon(data: dict):
    """把词表分成三类：句末助词、句首叹词、固定短语（不参与密度）。

    只有前两类算「主助词」；傲娇句型、鼓劲、笑声、叠词等属于风格短语，
    单独统计，避免把「才不是……哦」误判成两个助词。
    """
    final_words, initial_words, phrase_words = set(), set(), set()
    for category, words in data["density_categories"].items():
        if category.startswith("句末"):
            final_words.update(words)
        elif category in {"句首·思考停顿", "句首·惊讶感叹", "轻哼与不满"}:
            initial_words.update(words)
        else:
            phrase_words.update(words)

    for word in FINAL_OVERRIDES:
        phrase_words.discard(word)
        initial_words.discard(word)
        final_words.add(word)
    for word in INITIAL_OVERRIDES:
        phrase_words.discard(word)
        final_words.discard(word)
        initial_words.add(word)
    for word in ANYWHERE_OVERRIDES:
        final_words.discard(word)
        initial_words.discard(word)
        phrase_words.add(word)

    all_words = final_words | initial_words | phrase_words
    return final_words, initial_words, phrase_words, all_words


def exception_spans(text: str):
    spans = []
    for word in EXCEPTION_WORDS:
        start = text.find(word)
        while start != -1:
            spans.append((start, start + len(word)))
            start = text.find(word, start + 1)
    return spans


def overlap(start, end, spans) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def scan_clause(text: str, final_words, initial_words, phrase_words):
    """返回 [(word, start, end, kind)]，同一位置优先匹配更长的词。

    kind 为 modal（句末助词 / 句首叹词）或 phrase（风格短语）。
    """
    candidates = []
    for word in sorted(final_words | initial_words | phrase_words, key=len, reverse=True):
        start = text.find(word)
        while start != -1:
            candidates.append((start, start + len(word), word))
            start = text.find(word, start + 1)

    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    spans = exception_spans(text)
    chosen = []
    occupied = []
    for start, end, word in candidates:
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            continue
        if overlap(start, end, spans):
            continue
        kind = "phrase"
        if word in final_words:
            kind = "modal"
            if end < len(text) and text[end] not in BOUNDARY:
                continue
        elif word in initial_words:
            kind = "modal"
            if start > 0 and text[start - 1] not in BOUNDARY:
                continue
        occupied.append((start, end))
        chosen.append((word, start, end, kind))
    return sorted(chosen, key=lambda item: item[1])


def prose_view(raw: str) -> str:
    text = FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), raw)
    text = INLINE_CODE_RE.sub("", text)
    text = LINK_RE.sub(lambda m: m.group(1), text)
    text = TABLE_LINE_RE.sub("", text)
    return text


def scan_all(text: str, all_words):
    """不按位置、只找词：用于代码与表格的违规检查。"""
    found = []
    spans = exception_spans(text)
    for word in sorted(all_words, key=len, reverse=True):
        start = text.find(word)
        while start != -1:
            if not overlap(start, start + len(word), spans):
                found.append((word, start))
            start = text.find(word, start + 1)
    return found


def count_non_overlapping(text: str, words) -> int:
    """按最长优先统计，避免「其实吧」同时计入「其实」和「其实吧」。"""
    spans = []
    for word in sorted(words, key=len, reverse=True):
        start = text.find(word)
        while start != -1:
            if not overlap(start, start + len(word), spans):
                spans.append((start, start + len(word)))
            start = text.find(word, start + 1)
    return len(spans)


def first_hit_line(chunk: str, hits) -> str:
    hit_words = {word for word, _ in hits}
    for line in chunk.splitlines():
        if any(word in line for word in hit_words):
            return line.strip()[:100]
    return chunk.strip().splitlines()[0][:100] if chunk.strip() else ""


def count_kaomoji(text: str) -> int:
    total = 0
    for match in KAOMOJI_RE.finditer(text):
        if sum(char in KAOMOJI_CHARS for char in match.group(0)) >= 2:
            total += 1
    total += len(ASCII_KAOMOJI_RE.findall(text))
    return total


def load_target(style_id: str):
    if not STYLES_PATH.exists():
        return None, None
    data = load_json(STYLES_PATH)
    for item in data.get("styles", []):
        if item["id"].upper() == style_id.upper():
            return item.get("density"), f"{item['id']} {item['name']}"
    known = "、".join(item["id"] for item in data.get("styles", []))
    raise SystemExit(f"未知风格 id：{style_id}。可用：{known}")


def analyze(raw: str, style_id: str | None = None, strict: bool = False) -> dict:
    particles = load_json(PARTICLES_PATH)
    final_words, initial_words, phrase_words, all_words = build_lexicon(particles)

    prose = prose_view(raw)
    chars = len(CJK_RE.findall(prose))
    matches = []
    clause_issues = []

    for clause_match in CLAUSE_SPLIT_RE.finditer(prose):
        clause = clause_match.group(0)
        found = scan_clause(clause, final_words, initial_words, phrase_words)
        matches.extend(found)
        modal_in_clause = [item for item in found if item[3] == "modal"]
        if len(modal_in_clause) >= 2:
            clause_issues.append(
                {
                    "type": "每句助词过多",
                    "detail": "同一小句出现 %d 个主助词：%s"
                    % (len(modal_in_clause), "、".join(item[0] for item in modal_in_clause)),
                    "excerpt": clause.strip(),
                }
            )

    modal_matches = [item for item in matches if item[3] == "modal"]
    phrase_matches = [item for item in matches if item[3] == "phrase"]
    modal_count = len(modal_matches)
    phrase_count = len(phrase_matches)
    per_100 = round(modal_count / chars * 100, 1) if chars else 0.0
    structural = prose.count("的") + prose.count("了")
    discourse = count_non_overlapping(prose, particles.get("discourse_markers", []))
    kaomoji = count_kaomoji(raw)

    violations = list(clause_issues)

    # 堆叠检查（笑声「哈哈哈」除外）
    for repeated in re.finditer(r"([呢吧啊呀哦噢嘛啦呐喔哒嘞捏咩惹咯喽呗])\1{2,}", prose):
        violations.append(
            {
                "type": "助词堆叠",
                "detail": f"连续重复「{repeated.group(0)}」",
                "excerpt": repeated.group(0),
            }
        )

    # 代码块 / 行内代码
    code_chunks = FENCE_RE.findall(raw) + INLINE_CODE_RE.findall(raw)
    for chunk in code_chunks:
        hits = scan_all(chunk, all_words)
        if hits:
            violations.append(
                {
                    "type": "代码内出现助词",
                    "detail": "、".join(sorted({item[0] for item in hits}))[:80],
                    "excerpt": first_hit_line(chunk, hits),
                }
            )

    # 表格
    for line in TABLE_LINE_RE.findall(raw):
        hits = scan_all(line, all_words)
        if hits:
            violations.append(
                {
                    "type": "表格内出现助词",
                    "detail": "、".join(sorted({item[0] for item in hits}))[:80],
                    "excerpt": line.strip()[:120],
                }
            )

    # 链接文字
    for link_text in LINK_RE.findall(raw):
        hits = scan_all(link_text, all_words)
        if hits:
            violations.append(
                {
                    "type": "链接文字出现助词",
                    "detail": "、".join(sorted({item[0] for item in hits}))[:80],
                    "excerpt": link_text[:80],
                }
            )

    # 禁用词
    for word in particles.get("banned", []):
        occurrences = raw.count(word)
        if occurrences:
            violations.append(
                {
                    "type": "禁用词",
                    "detail": f"「{word}」出现 {occurrences} 次",
                    "excerpt": word,
                }
            )

    target, style_name = load_target(style_id) if style_id else (None, None)
    target_status = None
    if target:
        low, high = target
        if per_100 < low:
            target_status = "below"
        elif per_100 > high:
            target_status = "above"
        else:
            target_status = "in_range"

    density_ok = target_status in (None, "in_range")
    ok = not violations and (density_ok or not strict)

    modal_counter = Counter(item[0] for item in modal_matches)
    phrase_counter = Counter(item[0] for item in phrase_matches)
    return {
        "chars": chars,
        "modal_count": modal_count,
        "modal_per_100": per_100,
        "phrase_count": phrase_count,
        "structural_count": structural,
        "discourse_count": discourse,
        "kaomoji_count": kaomoji,
        "style": style_name,
        "target": target,
        "target_status": target_status,
        "matches": dict(modal_counter.most_common()),
        "phrases": dict(phrase_counter.most_common()),
        "short_text": chars < 100,
        "violations": violations,
        "ok": ok,
    }


def render(result: dict) -> str:
    lines = ["语气密度检测", ""]
    if result["style"]:
        lines.append(f"风格：{result['style']}")
    if result["target"]:
        low, high = result["target"]
        if low == high:
            lines.append(f"目标：{low} 次/百字（标准档）")
        else:
            lines.append(f"目标：{low}–{high} 次/百字（标准档）")
    lines.append(f"正文汉字：{result['chars']}")
    lines.append(f"主助词：{result['modal_count']} 次 → {result['modal_per_100']} 次/百字")
    if result["target_status"] == "in_range":
        lines.append("密度：区间内")
    elif result["target_status"] == "below":
        lines.append("密度：偏低")
    elif result["target_status"] == "above":
        lines.append("密度：偏高")
    lines.append(f"结构助词（的 / 了，不计入）：{result['structural_count']}")
    lines.append(
        f"风格短语：{result['phrase_count']}    口头禅：{result['discourse_count']}"
        f"    颜文字：{result['kaomoji_count']}"
    )
    if result["matches"]:
        lines.append("助词：" + "、".join(f"{word}×{count}" for word, count in result["matches"].items()))
    if result["phrases"]:
        lines.append("短语：" + "、".join(f"{word}×{count}" for word, count in result["phrases"].items()))
    if result["short_text"]:
        lines.append("注：文本不足 100 字，每百字密度波动较大，仅作趋势参考。")
    lines.append("")

    if result["violations"]:
        lines.append(f"规则问题（{len(result['violations'])}）：")
        for item in result["violations"]:
            lines.append(f"- [{item['type']}] {item['detail']}")
            if item.get("excerpt"):
                lines.append(f"  例：{item['excerpt']}")
    else:
        lines.append("规则问题：无")
    lines.append("")
    if result["ok"]:
        if result["target_status"] in {"below", "above"}:
            lines.append("结论：PASS（密度仅参考；加 --strict 可将其计入失败）")
        else:
            lines.append("结论：PASS")
    else:
        lines.append("结论：需要调整")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="检测语气助词密度与硬规则")
    parser.add_argument("file", nargs="?", help="待检测文本；省略则从 stdin 读取")
    parser.add_argument("--style", help="风格 id，如 S09，用于对比密度区间")
    parser.add_argument("--strict", action="store_true", help="密度超出区间也算失败")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    if args.file:
        try:
            raw = Path(args.file).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise SystemExit(f"找不到文件：{args.file}")
    else:
        if sys.stdin.isatty():
            raise SystemExit("请提供文本文件，或通过 stdin 传入文本。")
        raw = sys.stdin.read()

    result = analyze(raw, args.style, args.strict)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
