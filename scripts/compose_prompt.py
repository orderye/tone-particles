#!/usr/bin/env python3
"""生成单风格或融合风格的提示词片段，供系统提示词注入使用。

用法：
    python3 scripts/compose_prompt.py --main S04
    python3 scripts/compose_prompt.py --main S09 --accent S04 --weight-main 3 --weight-accent 2
    python3 scripts/compose_prompt.py --main S09 --accent S04 --accent S17 \
        --weight-main 3 --weight-accent 2 --density strong
    python3 scripts/compose_prompt.py --config config/user-config.json --history '["S01"]' --seed 7
    python3 scripts/compose_prompt.py --main S09 --accent S04 --json

输出默认为 Markdown，可直接追加到 system prompt 末尾。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: E402  本地模块，需先补 sys.path
import _context  # noqa: E402  语境策略：确定性、可解释的降档判断

DENSITY_FACTOR = _core.DENSITY_FACTOR
VARIANT_LABEL = {"gentle": "温柔型", "strict": "严厉型"}


def build_guidance(vector: dict) -> list:
    lines = []
    formality = vector.get("formality", 5)
    dominance = vector.get("dominance", 5)
    verbosity = vector.get("verbosity", 5)
    distance = vector.get("distance", 5)

    if formality >= 7:
        lines.append("句式偏完整、少网络词与叹号。")
    elif formality <= 2:
        lines.append("句式口语化，允许短句、口头禅与适量叹号。")
    else:
        lines.append("句式自然，正式与口语保持平衡。")

    if dominance >= 7:
        lines.append("语气采用「结论 / 理由 / 指令」的果断结构。")
    elif dominance >= 4:
        lines.append("语气采用「我建议……」的建议式，保留用户选择。")
    else:
        lines.append("语气采用「要不要试试……」的邀请式。")

    if verbosity >= 7:
        lines.append("可以展开细节与例子，但每段只讲一个重点。")
    elif verbosity <= 3:
        lines.append("结论优先，少铺垫，能一句说清就不写两句。")
    else:
        lines.append("按需展开，避免无意义铺陈。")

    if distance >= 7:
        lines.append("少寒暄、不主动闲聊，保持克制。")
    elif distance <= 2:
        lines.append("可以自然接话，但不过度热情。")
    return lines


def parse_members(args):
    """返回 [(id, weight), ...]，第一项为主风格。"""
    if not args.main:
        raise SystemExit("请用 --main 指定主风格，或提供 --config。")
    accents = []
    for accent in args.accent or []:
        sid = accent.upper()
        if sid not in accents and sid != args.main.upper():
            accents.append(sid)
    main_weight = args.weight_main if args.weight_main is not None else (4 if accents else 1)
    members = [(args.main.upper(), main_weight)]
    accent_weight = args.weight_accent if args.weight_accent is not None else 2
    for sid in accents:
        members.append((sid, accent_weight))
    return members


def resolve_from_config(args):
    """从配置文件解析本轮成员（[(id, weight), ...]）、密度与子模式。"""
    cfg = _core.load_config(args.config)
    history = []
    if args.history:
        try:
            history = json.loads(args.history)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"history 不是合法 JSON：{exc}")
    result = _core.pick(cfg, history, seed=args.seed)
    members = _core.members_with_weights(cfg, [result["main"]] + result["accents"])
    variants = cfg.get("variants", {})
    if not isinstance(variants, dict):
        variants = {}
    # --variant 作为覆盖项，不再被 --config 静默忽略。
    if args.variant:
        variants = {**variants, "S20": args.variant}
    return members, cfg.get("density", "standard"), variants


def compose(members, weights=None, density_level="standard", variants=None,
            context=None) -> dict:
    """对外的稳定入口。

    members 是 [(风格 id, 权重), ...]，第一项为主风格，最多 3 项。
    context 是可选的语境决策（见 scripts/_context.py）；给了就会写进提示词。
    返回提示词正文与结构化信息，供 CLI、宿主适配层与工具接口服务共用。
    """
    catalog_data, catalog = _core.load_catalog()
    members = [(str(sid).upper(), int(weight)) for sid, weight in members]
    if not members:
        raise SystemExit("至少要指定一个风格。")
    if len(members) > 3:
        members = members[:3]
    # 去重并剔除与主风格相同的副风格
    unique = [members[0]]
    for sid, weight in members[1:]:
        if sid not in [item[0] for item in unique]:
            unique.append((sid, weight))
    members = unique

    _core.validate_style_ids([sid for sid, _ in members], catalog)

    if weights is None:
        weights = [4] + [2] * (len(members) - 1) if len(members) > 1 else [1]
    else:
        weights = [int(item) for item in weights][:len(members)]

    density_level = density_level or "standard"
    factor = _core.density_factor(density_level)

    metas = [catalog[sid] for sid, _ in members]
    total_weight = sum(weights)
    shares = [weight / total_weight for weight in weights]
    texts = [_core.style_text(meta) for meta in metas]

    dimension_order = _core.dimension_order(catalog_data)
    dimension_labels = _core.dimension_labels(catalog_data)
    vector = {
        key: round(_core.weighted_average([meta["vector"][key] for meta in metas], weights), 1)
        for key in dimension_order
    }
    low, high = _core.density_range(metas, weights, factor)

    main_id = metas[0]["id"]
    active_ids = {meta["id"] for meta in metas}
    applied_variants = {
        sid: value for sid, value in (variants or {}).items() if sid in active_ids
    }

    prompt = build_prompt(
        metas, weights, shares, texts, vector, low, high,
        density_level, factor, catalog_data, applied_variants,
        dimension_order, dimension_labels, context
    )
    return {
        "mode": "blend" if len(metas) > 1 else "single",
        "density": density_level,
        "density_multiplier": factor,
        "density_range": [round(low, 2), round(high, 2)],
        "context": context or None,
        "members": [
            {
                "id": meta["id"],
                "name": meta["name"],
                "role": "main" if index == 0 else "accent",
                "weight": weights[index],
                "share": round(shares[index], 3),
                "file": meta["file"],
            }
            for index, meta in enumerate(metas)
        ],
        "vector": vector,
        "variants": applied_variants,
        "conflicts": [
            {"main": main_id, "accent": meta["id"]}
            for meta in metas[1:]
            if _core.conflict_note(main_id, meta["id"], catalog_data)
        ],
        "prompt": prompt,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成语气提示词（单一或融合）")
    parser.add_argument("--main", help="主风格 id，如 S09")
    parser.add_argument("--accent", action="append", help="副风格 id，可重复，最多 2 个")
    parser.add_argument("--weight-main", type=int, default=None,
                        help="主风格权重，默认 4（两个副风格时占一半）")
    parser.add_argument("--weight-accent", type=int, default=None, help="每个副风格权重，默认 2")
    parser.add_argument("--config", help="从 user-config.json 读取本轮风格")
    parser.add_argument("--history", help="配合 --config 使用的历史数组")
    parser.add_argument("--seed", type=int, default=None, help="配合 --config 的随机种子")
    parser.add_argument("--density", choices=sorted(DENSITY_FACTOR), help="覆盖密度档位")
    parser.add_argument("--variant", choices=["gentle", "strict"],
                        help="老师风格子模式（仅 S20）：gentle 温柔型 / strict 严厉型")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    density_level = args.density
    variants = {}
    if args.config:
        members, cfg_density, variants = resolve_from_config(args)
        density_level = density_level or cfg_density
    else:
        members = parse_members(args)
        if args.variant:
            variants = {"S20": args.variant}
    density_level = density_level or "standard"

    # parse_members 与 resolve_from_config 都已把权重写进 members，
    # 只有用户显式传了 --weight-* 才覆盖。
    weights = [weight for _, weight in members]
    if args.weight_main is not None:
        weights[0] = args.weight_main
    if args.weight_accent is not None:
        weights = [weights[0]] + [args.weight_accent] * (len(members) - 1)

    payload = compose(members, weights, density_level, variants)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["prompt"])
    return 0


def build_prompt(metas, weights, shares, texts, vector, low, high,
                 density_level, factor, catalog_data, variants=None,
                 dimension_order=None, dimension_labels=None, context=None) -> str:
    main_meta, main_text = metas[0], texts[0]
    accents = list(zip(metas[1:], texts[1:], shares[1:]))
    is_blend = bool(accents)
    lines = []

    lines.append("# 本轮语气指令（tone-particles 生成）")
    lines.append("")
    scope = "融合" if is_blend else "单一"
    lines.append(f"- 模式：{scope}")
    role_names = []
    for index, meta in enumerate(metas):
        role = "主" if index == 0 else "副"
        role_names.append(
            f"{meta['id']} {meta['name']}（{role}，权重 {weights[index]}，{shares[index] * 100:.0f}%）"
        )
    lines.append("- 风格：" + "、".join(role_names))
    for sid, value in (variants or {}).items():
        label = VARIANT_LABEL.get(value, value)
        name = next((meta["name"] for meta in metas if meta["id"] == sid), sid)
        lines.append(f"- 子模式：{sid} {name} — {label}")
    lines.append(f"- 密度：{density_level}（×{factor:g}），参考 {_core.format_range(low, high)} 次/百字")
    order = dimension_order or []
    labels = dimension_labels or {}
    vector_text = " / ".join(
        f"{labels.get(key, key)} {vector[key]:g}" for key in order
    )
    lines.append(f"- 融合向量：{vector_text}")
    lines.append("")

    lines.append("## 通用规则（优先于风格）")
    lines.append("")
    lines.append("- 先写出完整准确的答案，再套语气；删掉全部语气词后信息必须完整不变。")
    lines.append("- 每句（小句）最多 1 个主助词，不堆叠；代码块、行内代码、表格、链接、数字、公式、专有名词内零助词。")
    lines.append("- 场景自适应：代码与高风险信息保持中性；用户情绪低落时降档；危机信号时完全关闭风格。")
    lines.append("- 安全边界：风格只是口吻，不是身份；不声明年龄、不扮演未成年人或恋人 / 家人关系位；"
                 "强势风格不辱骂、不操控；暗黑不渲染自伤与暴力。完整规则见 references/safety.md。")
    lines.append("")

    # 语境策略：确定性判断的结果写进提示词，让模型知道这一轮的强度要求。
    if context:
        note = _context.prompt_note(context)
        if note:
            lines.append("## 语境策略")
            lines.append("")
            lines.append(f"- {note}")
            lines.append("")

    if context and context.get("style_off"):
        # 危机等场景：完全关闭风格。风格全文不再下发——下发它等于在教模型
        # 用一个它此刻不该用的腔调说话。
        lines.append("## 本轮不使用任何风格")
        lines.append("")
        lines.append("- 不用语气助词、颜文字、口头禅、角色腔调，也不用称呼与自称的变化。")
        lines.append("- 用平实、直接、关切的语言回应；不回避、不说教、不轻描淡写。")
        lines.append("- 直接询问安全：「你现在安全吗？」「你现在有伤害自己的打算吗？」不要害怕问。")
        lines.append("- 鼓励立即联系身边的人，并给出求助渠道：紧急危险拨打 120（急救）或 110（报警）；"
                     "中国大陆心理援助热线 12356；其他地区拨当地急救号码或自杀预防热线。")
        lines.append("- 不承诺保密到危及生命的程度；不独自承担危机干预。")
        lines.append("- 用户脱离危机后也不立即恢复风格，先确认状态。")
        lines.append("")
        lines.append("## 输出前检查")
        lines.append("")
        lines.append("- [ ] 没有任何语气成分。")
        lines.append("- [ ] 事实、求助渠道与安全提示完整。")
        return "\n".join(lines)

    if is_blend:
        main_share = shares[0] * 100
        lines.append("## 融合规则")
        lines.append("")
        lines.append(f"1. 主风格 {metas[0]['id']}「{metas[0]['name']}」贯穿全文，"
                     f"约 {main_share:.0f}% 的词库与句式来自主风格。")
        lines.append("2. 每个副风格只贡献 1 个签名元素；同一句话内不混搭两种腔调，按句交替。")
        lines.append("3. 先写出完整准确的答案，再套语气；删掉语气词后信息必须不变。")
        lines.append("4. 禁用词取并集；称呼与自称只用主风格的设定。")
        conflict_hits = [
            meta for meta, _, _ in accents
            if _core.conflict_note(metas[0]["id"], meta["id"], catalog_data)
        ]
        if conflict_hits:
            names = "、".join(item["name"] for item in conflict_hits)
            lines.append(
                f"5. 主副风格差异较大（{names}）：采用**反差融合**，副风格只在被夸奖、"
                "被问私人感受、出小状况、道谢告别这四类触发点出现一句，随后立即回到主风格。"
            )
        lines.append("")
        lines.append("### 表达参数")
        lines.append("")
        lines.extend(f"- {item}" for item in build_guidance(vector))
        lines.append("")

    lines.append(f"## 主风格全文（{main_meta['id']} {main_meta['name']}）")
    lines.append("")
    lines.append(main_text.strip())
    lines.append("")

    for meta, text, share in accents:
        signature = _core.extract_signature(text) or "；".join(meta.get("signature", []))
        common = _core.extract_common_words(_core.extract_field(text, "词库"))
        positioning = _core.extract_positioning(text)
        kaomoji = _core.extract_kaomoji_line(text)
        lines.append(f"## 副风格素材（{meta['id']} {meta['name']}，{share * 100:.0f}%）")
        lines.append("")
        lines.append(f"- 定位：{positioning}。")
        lines.append(f"- 签名元素（最多借用 1 个）：{signature}")
        lines.append(f"- 可用词：{common}")
        if kaomoji:
            lines.append(f"- 颜文字库（仅开启时，最多借 1 个）：{kaomoji}")
        lines.append("- 不要整段模仿副风格，也不要让副风格主导句子结构。")
        lines.append("")

    lines.append("## 输出前检查")
    lines.append("")
    lines.append("- [ ] 删掉语气词后，事实、结论、代码、数字仍然完整。")
    lines.append("- [ ] 代码块、行内代码、表格、链接内没有助词。")
    lines.append("- [ ] 每句（小句）最多 1 个主助词，没有堆叠。")
    lines.append("- [ ] 场景自适应与安全边界已检查；危机信号时已关闭风格。")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
