#!/usr/bin/env python3
"""确定性语境策略。

回答一个问题：**这一轮该用多强的语气说话？**

判断全部在本地完成——不上传用户消息、不调用模型、不猜用户心理。命中规则时给出
可解释的 reason code，日志与评测都能知道「为什么降档」。

## 优先级（与 references/safety.md 对齐）

1. **危机信号** —— 安全硬规则：完全关闭风格。不能被任何配置、任何宿主元数据关闭。
2. **不可改写区域与结构化输出** —— 代码 / 表格：正文中性，密度降到轻档。
3. **明确的暂停设置** —— 由宿主的 `paused` 处理，不在本模块（两者语义不同：
   暂停是「不施加风格」，危机是「即使风格开启也要限制强度」）。
4. **正式程度与任务场景** —— 高风险、正式写作、报错排查、情绪低落。
5. **用户配置的风格、融合权重与密度** —— 宿主的配置。
6. **默认风格策略** —— 什么都不命中时保持原样。

## 判断原则

- 区分「任务本身就是这类东西」和「用户在闲聊里提到这类东西」。
  「帮我写一封邮件」是正式写作；「邮件系统怎么配置」不是。
- 不确定的场景走中性默认（不改密度），不靠猜用户心理来调口吻。
- 自动分类可以被关闭（配置 `scene_adapt: false`）或被宿主提供的结构化元数据覆盖，
  但**危机硬规则不能被关闭**。

纯标准库，无第三方依赖。
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# 场景与策略
# --------------------------------------------------------------------------

# 场景 → 策略。density 为 None 表示不覆盖配置里的档位。
# style_off 为 True 表示这一轮完全关闭风格。
POLICY = {
    "crisis": {
        "density": None, "style_off": True, "priority": 1,
        "label": "危机信号",
        "reason": "检测到危机信号：按安全规则完全关闭风格，用平实关切的口吻回应。",
    },
    "code": {
        "density": "light", "style_off": False, "priority": 2,
        "label": "代码 / 排障",
        "reason": "检测到代码或排障任务：正文保持中性，密度降到轻档，代码与命令内零助词。",
    },
    "table": {
        "density": "light", "style_off": False, "priority": 2,
        "label": "表格 / 结构化输出",
        "reason": "检测到表格或结构化输出任务：表格内零助词，表前表后保持中性。",
    },
    "high_risk": {
        "density": "light", "style_off": False, "priority": 4,
        "label": "高风险信息",
        "reason": "检测到医疗 / 法律 / 金融等高风险内容：降到轻档，关键提示用中性措辞。",
    },
    "formal": {
        "density": "light", "style_off": False, "priority": 4,
        "label": "正式写作",
        "reason": "检测到正式文档写作任务：降到轻档，开头结尾可以带一句语气。",
    },
    "error_steps": {
        "density": "light", "style_off": False, "priority": 4,
        "label": "报错 / 排查步骤",
        "reason": "检测到报错或排查步骤：步骤中性，首尾带语气。",
    },
    "low_mood": {
        "density": "light", "style_off": False, "priority": 4,
        "label": "情绪低落",
        "reason": "检测到情绪低落：收起夸张风格，温和低密度，不否定情绪。",
    },
    "non_chinese": {
        "density": None, "style_off": True, "priority": 4,
        "label": "非中文内容",
        "reason": "输入不含中文：暂停中文助词。",
    },
    "normal": {
        "density": None, "style_off": False, "priority": 6,
        "label": "普通对话",
        "reason": "未命中任何场景规则，按配置正常作答。",
    },
}

SCENES = tuple(POLICY)

# 宿主可以显式指定的场景（不含 crisis——安全硬规则不接受覆盖）。
EXPLICIT_SCENES = tuple(name for name in SCENES if name != "crisis")

# --------------------------------------------------------------------------
# 信号
# --------------------------------------------------------------------------

# 危机信号。分两档：
# - 强信号本身就是危机信号（自杀、自残等），命中即降级；
# - 弱信号需要同时出现绝望 / 告别的语境才算数——「这 bug 我想死了」是吐槽，
#   不是危机，误判会把风格白白关掉。
CRISIS_STRONG_RE = re.compile(
    r"(自杀|割腕|跳楼|自残|轻生|结束(?:自己的)?生命|了结自己|伤害自己"
    r"|不想活了|活不下去)")

CRISIS_WEAK_RE = re.compile(
    r"(活着没意思|想死|不想再醒过来|结束这一切|一了百了)")

# 危机语境：绝望、告别、终结。
CRISIS_CONTEXT_RE = re.compile(
    r"(绝望|没意义|没意思|撑不下去|告别|再也|再也不|永远离开|离开这个世界|结束算了|算了)")

# 任务动词：出现它才说明「这一轮要产出东西」，而不是聊到相关话题。
ARTIFACT_ACTION_RE = re.compile(
    r"(帮我|给我|替我|帮忙)?\s*(?:写|起草|生成|整理|列|做|输出|润色|改写|制作|出|拟)"
    r"\s*(?:一份|个|张|篇|段|条|封|套|点|些)?")

# 弱任务动词：用在「弱信号 + 需要做一件事」的组合上。
# 「今天写代码好累」里有「写」，但那不是一次技术求助——所以弱信号路径用更严的
# 动词集。
TASK_ACTION_RE = re.compile(
    r"(帮我|给我|替我|怎么|如何|为什么|能不能|可不可以|要不要|请|排查|解决|修复|调试)")

# 代码 / 排障的强信号：几乎只出现在真正的技术任务里。
CODE_STRONG_RE = re.compile(
    r"(```|这段代码|这段程序|报错|报了个|异常|traceback|stack\s*trace|堆栈"
    r"|编译错误|语法错误|跑不起来|不生效|函数|方法|变量|类|接口返回|返回值"
    r"|正则|sql|索引|内存|并发|死锁|端口|日志|单元测试|调试|重构)")

# 弱信号：只有在同时出现「要做一件事」的动词时才算技术任务。
CODE_WEAK_RE = re.compile(
    r"(代码|程序|bug|程序|部署|上线|服务器|脚本|命令|docker|git|python|java|sql)")

TABLE_RE = re.compile(r"(表格|对比表|列一张表|列一个表|做成表|统计表|数据表|清单表)")

HIGH_RISK_RE = re.compile(
    r"(吃什么药|用药|剂量|处方|副作用|诊断|确诊|症状|手术|化疗|放疗|怀孕|哺乳"
    r"|血糖|血压|心悸|失眠|抑郁|伤口|急救|起诉|判刑|违法|刑事责任|诉讼|合同纠纷"
    r"|投资|股票|基金|理财|加密货币|比特币|杠杆|亏损)")

FORMAL_NOUN_RE = re.compile(
    r"(邮件|公告|公文|声明|通知|报告|方案|策划案|简历|白皮书|说明书|合同|邀约函"
    r"|说明|提纲|笔记|总结|文案|文章|短文|清单|计划|行程)")

ERROR_STEPS_RE = re.compile(
    r"(排查|定位问题|怎么修|怎么解决|解决不了|还是不行|不生效|失败了|起不来"
    r"|连不上|报错了|出错了)")

LOW_MOOD_RE = re.compile(
    r"(难过|难受|崩溃|撑不住|撑不下去|沮丧|提不起兴趣|提不起劲|想哭|委屈|失落"
    r"|不开心|心情不好|压力好大|压力很大|没考上|落榜|被批评|被骂|只有你"
    r"|没人可以说|不想说话)")

CJK_RE = re.compile(r"[一-鿿]")


# --------------------------------------------------------------------------
# 判断
# --------------------------------------------------------------------------


def is_crisis(text: str) -> bool:
    """这条输入是不是危机信号。

    强信号（自杀、自残等）命中即算；弱信号（不想活、想死等）还要同时出现
    绝望 / 告别的语境才算——「这 bug 我想死了」是吐槽，不是危机。误判的代价是
    把风格白白关掉，所以宁可保守一点。
    """
    if CRISIS_STRONG_RE.search(text):
        return True
    return bool(CRISIS_WEAK_RE.search(text) and CRISIS_CONTEXT_RE.search(text))


def _looks_like_tech_task(text: str) -> bool:
    """弱信号（提到代码 / 程序）是否伴随一次真正的技术求助。"""
    return bool(TASK_ACTION_RE.search(text))


def detect(user_input: str) -> str:
    """自动检测场景。返回 SCENES 里的一个名字。

    只做文本层面的确定性判断；命中顺序即优先级，危机最先看。
    """
    text = str(user_input or "")
    if not text.strip():
        return "normal"

    if is_crisis(text):
        return "crisis"
    if not CJK_RE.search(text):
        return "non_chinese"

    if CODE_STRONG_RE.search(text) or (CODE_WEAK_RE.search(text) and _looks_like_tech_task(text)):
        return "code"
    if TABLE_RE.search(text):
        return "table"
    if HIGH_RISK_RE.search(text):
        return "high_risk"
    if ERROR_STEPS_RE.search(text):
        return "error_steps"
    if FORMAL_NOUN_RE.search(text) and ARTIFACT_ACTION_RE.search(text):
        return "formal"
    if LOW_MOOD_RE.search(text):
        return "low_mood"
    return "normal"


def resolve(user_input: str = "", *, explicit=None, scene_adapt: bool = True) -> dict:
    """解析本轮的语境决策。

    explicit 是宿主提供的结构化元数据（例如 {"scene": "code"}）：
    - 显式指定的场景覆盖自动检测；
    - 但危机硬规则不受影响——自动检测到危机就一定是危机，宿主说「不是」也不行。

    scene_adapt 为 False 时关闭自动分类（宿主不需要语境策略时用）。
    危机规则始终生效。
    """
    detected = detect(user_input)
    explicit_scene = None
    if isinstance(explicit, dict):
        value = explicit.get("scene")
        if value:
            explicit_scene = str(value)

    if explicit_scene:
        if explicit_scene not in SCENES:
            raise SystemExit(
                f"未知场景：{explicit_scene}。可用：{'、'.join(SCENES)}")
        if detected == "crisis":
            # 安全硬规则：显式元数据不能把危机降级成别的场景。
            scene = "crisis"
            source = "auto"
        else:
            scene = explicit_scene
            source = "explicit"
    elif detected == "crisis":
        scene = "crisis"
        source = "auto"
    elif not scene_adapt:
        scene = "normal"
        source = "disabled"
    else:
        scene = detected
        source = "auto"

    policy = POLICY[scene]
    reason = policy["reason"]
    if scene == "crisis" and source == "auto" and explicit_scene:
        reason += "（宿主指定的场景未覆盖安全硬规则。）"
    return {
        "scene": scene,
        "label": policy["label"],
        "reason_code": scene,
        "reason": reason,
        "density_level": policy["density"],
        "style_off": policy["style_off"],
        "priority": policy["priority"],
        "source": source,
    }


def prompt_note(context: dict) -> str:
    """把语境决策写成提示词里的一行，供模型知道这一轮的强度要求。"""
    if not context:
        return ""
    if context.get("style_off"):
        return (f"本轮完全关闭风格（{context.get('label')}）："
                "不用语气助词、颜文字、口头禅与角色腔调，用平实直接的语气作答。")
    if context.get("density_level"):
        return (f"本轮语境：{context.get('label')}——{context.get('reason')}"
                f"语气降到「{context['density_level']}」档。")
    return ""
