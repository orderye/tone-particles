# 语气助词 Skill（tone-particles）

版本 0.1.0 ｜ 对应 PRD v0.1 ｜ 21 种中文口吻风格

仓库：[GitHub](https://github.com/orderye/tone-particles) ｜ [CNB 镜像](https://cnb.cool/toroyxxx/tone-particles) ｜ [Releases](https://github.com/orderye/tone-particles/releases)

在不改变回答内容的前提下，给 AI 的中文对话加上有辨识度的语气。支持单一、融合、随机轮换、融合随机四种模式，带密度调节、颜文字、场景自适应与安全边界。

## 特性

- **21 种风格**：御姐、萌妹、少女、邻家、高冷、三无、元气、天然呆、傲娇、女王、贤惠、萝莉、辣妹、酷飒、古典、暗黑、知性、学姐、学妹、老师、大小姐。
- **四种运行模式**：固定一种、按权重融合、随机轮换、融合随机。
- **内容保真**：先答后套；助词只作用于表达层，不进入代码、表格、数字与专有名词。
- **场景自适应**：代码、医疗、法律、情绪低落、危机信号时自动降档或关闭。
- **可复现的随机**：由脚本按权重与去重窗口抽样，模型只负责表达。
- **可测试**：自带密度与硬规则检测脚本，另有一套端到端评测（`eval/`）。
- **共享核心**：三个 CLI 共用 `scripts/_core.py`，配置、密度区间与抽样语义只有一处定义。

## 目录

```
tone-particles/
├── SKILL.md                 # 入口：触发条件、每轮流程、硬规则
├── README.md
├── config/
│   ├── defaults.json        # 默认配置
│   ├── user-config.example.json
│   ├── styles.json          # 21 风格的向量、密度、签名元素
│   └── particles.json       # 机器可读词表
├── styles/
│   ├── S01-yujie.md
│   └── ...                  # 共 21 个
├── references/
│   ├── lexicon.md           # 助词、标点、颜文字
│   ├── fusion-rules.md      # 融合、冲突、随机、降级
│   ├── safety.md            # 安全边界与危机处理
│   └── onboarding.md        # 导入向导
├── scripts/
│   ├── _core.py             # 共享核心：配置、风格目录、密度区间、抽样
│   ├── pick_style.py        # 随机 / 加权选风格
│   ├── compose_prompt.py    # 生成融合提示词
│   └── check_density.py     # 密度与硬规则检测
├── eval/                    # 评测体系（不随包分发）
│   ├── run.py               # 评测入口
│   ├── cases/               # 用例集
│   ├── judge/               # 各指标判分器
│   └── backends/            # 模型后端（可缺席）
├── Docs/                    # PRD 与部署方案（不随包分发）
└── dist/                    # 打包好的 zip（不随包分发）
```

用户配置 `config/user-config.json` 在首次导入后生成，不随包分发；随机模式还会生成 `config/tone-history.json`，记录最近使用的风格，避免连续重复。`dist/` 下是打包好的 zip。

## 安装

### 通用安装

本仓库的根目录就是完整的 skill 包，克隆到所用平台的 skills 目录即可直接使用：

```bash
# 个人级（所有项目可用）
mkdir -p ~/.skills
git clone https://github.com/orderye/tone-particles.git ~/.skills/tone-particles

# 项目级（只对当前仓库生效）
mkdir -p .skills
git clone https://github.com/orderye/tone-particles.git .skills/tone-particles
```

国内网络可用 CNB 镜像：

```bash
git clone https://cnb.cool/toroyxxx/tone-particles.git ~/.skills/tone-particles
```

也可以直接下载 Release 里的 `tone-particles-0.1.0.zip` 解压后放入 skills 目录。

手动复制的方式同样可用，在 `tone-particles` 的上一级目录执行：

```bash
mkdir -p ~/.skills && cp -R tone-particles ~/.skills/
```

放好后重启会话，或等平台重新扫描 skills。之后说「换个语气」「调整说话风格」「重新配置语气」即可触发。

各平台的 skills 目录位置与加载方式可能不同，以对应平台的官方文档为准。

### 支持 zip 导入的平台

直接上传 `dist/tone-particles-0.1.0.zip`（zip 顶层是 `tone-particles/` 目录，`SKILL.md` 位于该目录内）。不同版本的 Skills 入口位置可能变化，以官方文档为准。

### 任意对话应用（系统提示词注入）

由宿主程序每轮调用 `compose_prompt.py`，把输出追加到 system prompt：

```python
import json, subprocess

out = json.loads(subprocess.check_output([
    "python3", "/path/to/tone-particles/scripts/compose_prompt.py",
    "--config", "/path/to/tone-particles/config/user-config.json",
    "--history", json.dumps(history),          # 近几轮的风格 id
    "--json",
]).decode("utf-8"))

system_prompt = base_system_prompt + "\n\n" + out["prompt"]
history.append(out["members"][0]["id"])
```

同一 `history` + `seed` 的结果可复现。随机由宿主控制，最稳定。

### 工具接口

计划中（PRD 方案 C），当前版本未实现。

## 首次使用

首次触发时，skill 检测不到 `config/user-config.json`，会进入导入向导：

1. 选模式（单一 / 融合 / 随机轮换 / 融合随机）。
2. 从 6 个分组中选风格（单一 1 个；其他模式 2–21 个；融合最多 3 个）。
3. 调参数（密度、权重、随机粒度、颜文字开关）。
4. 用「帮我安排明天的日程」预览。
5. 确认后写入 `config/user-config.json`。

任何时候说「重新配置」都能回到向导。

## 日常控制

| 说 | 效果 |
| --- | --- |
| 「换成傲娇」「加一点元气」「只用知性和学姐」 | 改风格池 |
| 「语气浓一点 / 淡一点」 | 改密度档位 |
| 「先别换了」/「继续随机」 | 锁定 / 解锁切换 |
| 「暂停语气」/「恢复语气」 | 暂停 / 恢复整个 skill |
| 「现在是什么风格？」 | 查看当前模式与风格 |
| 「开启颜文字」「颜文字少一点」「关掉颜文字」 | 改颜文字设置 |
| 「老师严厉一点 / 温柔一点」 | 切换 S20 子模式 |
| 「重新配置」 | 重新进入向导 |

## 配置

```json
{
  "version": 1,
  "mode": "blend_random",
  "styles": [
    { "id": "S09", "weight": 3 },
    { "id": "S04", "weight": 2 },
    { "id": "S17", "weight": 1 }
  ],
  "variants": {},
  "density": "standard",
  "switch": {
    "granularity": "per_message",
    "no_repeat_window": 3,
    "locked": false
  },
  "scene_adapt": true,
  "kaomoji": { "enabled": false, "level": "light" },
  "emoji": "style_default",
  "paused": false
}
```

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `mode` | `single` / `blend` / `rotate` / `blend_random` | 运行模式 |
| `styles[].weight` | 正整数 | 抽样权重；融合时决定配比 |
| `variants` | `{"S20": "gentle"}` / `{"S20": "strict"}` | 老师子模式；其他风格留空 |
| `density` | `light` / `standard` / `strong` | 密度系数 0.5 / 1 / 1.5 |
| `switch.granularity` | `per_message` / `per_n_turns` / `on_topic_change` / `per_session` | 切换粒度 |
| `switch.no_repeat_window` | 0–10 | 最近 K 条不重复；0 表示允许连续重复 |
| `switch.locked` | 布尔 | 锁定当前风格 |
| `kaomoji.enabled` / `level` | 布尔 / `light` / `normal` | 颜文字开关与档位 |
| `paused` | 布尔 | 暂停语气层 |

`config/styles.json` 中每种风格带独立 `version` 与向量，升级时可单独替换某个风格文件而不影响其他风格。`config/particles.json` 是 `check_density.py` 的机器可读词表。

## 脚本

三个脚本都只依赖 Python 标准库（3.9+）。

### pick_style.py

```bash
# 按配置抽一次
python3 scripts/pick_style.py config/user-config.json '["S01","S09"]' --seed 42 --pretty

# 跨轮持久化：读历史并写回
python3 scripts/pick_style.py config/user-config.json \
    --history-file config/tone-history.json --append-history

# 查看 21 风格目录
python3 scripts/pick_style.py --catalog

# 模拟 1000 次，检查连续重复与权重偏差
python3 scripts/pick_style.py config/user-config.json '[]' --simulate 1000 --seed 42
```

输出包含 `main`、`accents`、`history` 与 `notes`。随机只由脚本完成，模型不自行「掷骰子」。

### compose_prompt.py

```bash
# 单一风格
python3 scripts/compose_prompt.py --main S04

# 融合：主 S09 + 副 S04
python3 scripts/compose_prompt.py --main S09 --accent S04 --weight-main 3 --weight-accent 2

# 从配置直接生成本轮提示词
python3 scripts/compose_prompt.py --config config/user-config.json --history '["S01"]' --seed 7

# 机器可读
python3 scripts/compose_prompt.py --main S09 --accent S04 --json
```

输出为 Markdown，可直接拼到 system prompt 末尾；`--json` 会额外给出成员、权重、融合向量与冲突提示。

### check_density.py

```bash
python3 scripts/check_density.py reply.txt --style S09
cat reply.txt | python3 scripts/check_density.py --style S02 --json
python3 scripts/check_density.py reply.txt --style S09 --strict
```

检测内容：

- 主助词密度（次/百字），并与 `config/styles.json` 的目标区间对比。
- 每小句 ≤ 1 个主助词。
- 助词堆叠（「呢呢呢」）。
- 代码块、行内代码、表格、链接文字内是否出现助词。
- 全局禁用词、颜文字数量。

退出码：无规则问题为 0，有规则问题为 1；加 `--strict` 时密度超出区间也算失败。

**密度口径**：只统计句末助词与句首叹词（吧、呢、啊、呀、嗯、哼……）。傲娇句型、鼓劲、笑声、叠词等「风格短语」单独统计，不计入密度；「的 / 了」作为结构助词单独统计。少于 100 字的文本密度波动大，只作趋势参考。

## 测试

```bash
# 配置与风格文件完整性
python3 - <<'PY'
import json, pathlib
root = pathlib.Path(".")
styles = json.loads((root/"config/styles.json").read_text(encoding="utf-8"))["styles"]
assert len(styles) == 21, len(styles)
for item in styles:
    path = root/item["file"]
    assert path.exists(), path
    text = path.read_text(encoding="utf-8")
    for field in ["定位", "词库", "签名元素", "颜文字"]:
        assert field in text, (path, field)
print("OK: 21 styles, all files complete")
PY

# 随机与权重
python3 scripts/pick_style.py config/user-config.example.json '[]' --simulate 1000 --seed 42

# 密度与硬规则（从 stdin 传入待检文本）
printf '哼，这种小问题还要我看吗……算了。第 8 行少了个括号，改完就能跑了。\n' \
  | python3 scripts/check_density.py --style S09

# 端到端评测（确定性指标；需模型的三项标为「未评测」）
python3 eval/run.py
```

## 设计说明与已知限制

- **风格提示词是参考实现**：向量与密度区间来自 PRD 初始设定，正式上线前应按 PRD M4 做盲测校准。
- **单风格体积**：每个风格文件约 650–900 汉字（含标点与颜文字约 1.1–1.4k 字符），符合 PRD 的 900 字目标——代价是保留了完整的分场景细则、示例与反例。若需进一步压缩，可删去「更多示例」与「反例」两节。
- **随机与权重存在数学取舍**：要求「零连续重复」时，各风格的长期占比无法完全等于设定权重；池子不大于去重窗口时尤其明显。脚本会优先保证不连续重复，并在 `notes` 中说明。若更看重权重精确，把 `no_repeat_window` 设为 0。
- **密度区间是趋势指标**：短回复的每百字密度天然偏高。PRD 附录里的参考示例多为 20–60 字短句，按本工具口径普遍高于标称区间；M4 标定时应以 150–400 字的完整回复重新取样。硬性验收应看「每句 ≤ 1 个主助词」「代码 / 表格内为零」等可判定规则。
- **颜文字依赖字体**：不同平台显示不一致，默认关闭；出现乱码时按 `references/lexicon.md` 退回纯 ASCII。
- **不改变内容**：本 skill 只改表达层，但不能替代事实核查与安全审查。
- **系统提示词注入需要宿主开发**：`compose_prompt.py` 已提供拼装能力，调用时机、历史维护与缓存由宿主负责。

## 安全

风格只是口吻，不是身份或关系。不声明年龄、不扮演未成年人或恋人 / 家人关系位；强势风格不辱骂、不操控；暗黑风格不渲染自伤与暴力；用户出现危机信号时立即关闭风格并给出求助方向。完整规则见 `references/safety.md`，其优先级高于任何风格与配置。

## 版本

- `0.1.0`：21 风格、四种模式、导入向导、融合 / 随机、场景自适应、颜文字、三个脚本。对应 PRD M1–M3。
- 后续：M4 盲测与安全红队、M5 打包联调、M6 工具接口版。
