# 语气助词 Skill（tone-particles）

版本 0.4.0 ｜ 21 种中文口吻风格 ｜ 四种运行模式 ｜ Python 3.9+ ｜ 零第三方依赖

仓库：[GitHub](https://github.com/orderye/tone-particles) ｜ [CNB 镜像](https://cnb.cool/toroyxxx/tone-particles) ｜ [Releases](https://github.com/orderye/tone-particles/releases)

在不改变回答内容的前提下，给 AI 的中文对话加上有辨识度的语气。支持单一、融合、随机轮换、融合随机四种模式，带密度调节、颜文字、场景自适应与安全边界。

## 30 秒上手

```bash
git clone https://github.com/orderye/tone-particles.git ~/.skills/tone-particles
```

国内网络用 CNB 镜像：`git clone https://cnb.cool/toroyxxx/tone-particles.git ~/.skills/tone-particles`

放好后重启会话（或等平台重新扫描 skills），然后说「换个语气」「调整说话风格」即可触发。首次触发会进入导入向导，选好模式与风格即可开始。

不想装 skill、只想在自家应用里用，见 [接入方式](#接入方式)。

## 特性

- **21 种风格**：御姐、萌妹、少女、邻家、高冷、三无、元气、天然呆、傲娇、女王、贤惠、萝莉、辣妹、酷飒、古典、暗黑、知性、学姐、学妹、老师、大小姐。
- **四种运行模式**：固定一种、按权重融合、随机轮换、融合随机。
- **内容保真**：先答后套；助词只作用于表达层，不进入代码、表格、数字与专有名词。
- **场景自适应**：代码、表格、高风险信息、正式写作、报错排查、情绪低落时自动降档；危机信号时完全关闭风格。判断由共享核心里可审计的确定性规则完成（`scripts/_context.py`），带可解释的 reason code，**危机规则不可被任何配置或宿主元数据关闭**。见 [`Docs/语境策略与场景优先级.md`](Docs/语境策略与场景优先级.md)。
- **可复现的随机**：由脚本按权重与去重窗口抽样，同一配置 + 历史 + seed 结果一致；模型只负责表达，不自行「掷骰子」。
- **配置写得稳**：原子写入 + 跨进程锁 + 写前写后校验，并发更新不会写坏配置，写入失败不会返回「保存成功」。
- **可测试**：密度与硬规则检测脚本、端到端评测体系（`eval/`）、子进程级协议契约测试。
- **共享核心**：CLI、宿主适配层、MCP 服务共用 `scripts/_core.py`，配置、密度区间与抽样语义只有一处定义。
- **三种接入形态**：Skill 包、系统提示词注入、MCP 工具，共用同一份 `styles/` 与 `scripts/`，风格在任何形态下完全一致。

## 目录

```
tone-particles/
├── SKILL.md                 # 入口：触发条件、每轮流程、硬规则
├── README.md
├── VERSION                  # 版本单一来源（不随包分发）
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
│   ├── _context.py          # 语境策略：确定性的场景判断与降档
│   ├── pick_style.py        # 随机 / 加权选风格
│   ├── compose_prompt.py    # 生成融合提示词
│   └── check_density.py     # 密度与硬规则检测
├── eval/                    # 评测体系（不随包分发）
│   ├── run.py               # 评测入口
│   ├── validate_cases.py    # 用例结构校验
│   ├── report.py            # 报告渲染（.md + .json）
│   ├── generate.py          # 生成回复（需要模型）
│   ├── make_blind_sheet.py  # 人工盲测表
│   ├── cases/               # 用例集
│   ├── judge/               # 各指标判分器
│   ├── backends/            # 模型后端（可缺席）
│   └── fixtures/            # 存档回复与人工评审结果
├── integrations/            # 宿主接入包（不随包分发）
│   ├── tone_core/           # 核心能力的 Python API
│   ├── host_adapter.py      # 参考宿主适配器
│   ├── host_cli.py          # JSON over stdio，给非 Python 宿主
│   └── demo_loop.py         # 可跑的端到端演示
├── mcp/                     # MCP 服务（不随包分发）
│   ├── server.py            # JSON-RPC 2.0 over stdio
│   ├── tools.py             # 四个工具
│   └── schemas.py           # 工具的入参 schema
├── tools/                   # 仓库工具（不随包分发）
│   ├── selfcheck.py         # 自检：配置、风格一致性、CLI、单元测试
│   ├── package.py           # 构建并校验分发包
│   └── version.py           # 版本号四处同步
├── tests/                   # 单元测试（不随包分发，8 个文件）
├── Docs/                    # 指南与记录（不随包分发）
└── .github/workflows/       # GitHub Actions（不随包分发）
```

**分发包只有 36 个文件**：README、SKILL.md、`config/` 4 个、`references/` 4 个、`scripts/` 5 个、`styles/` 21 个。`eval/`、`integrations/`、`mcp/`、`tools/`、`tests/`、`Docs/` 都不进包。

用户配置 `config/user-config.json` 在首次导入后生成；随机模式还会生成 `config/tone-history.json`，记录最近使用的风格，避免连续重复。两者都不随包分发。分发 zip 只挂在 Releases 页，不进仓库（由 `tools/package.py` 构建）。

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

手动复制同样可用，在 `tone-particles` 的上一级目录执行：

```bash
mkdir -p ~/.skills && cp -R tone-particles ~/.skills/
```

各平台的 skills 目录位置与加载方式可能不同，以对应平台的官方文档为准。

### 支持 zip 导入的平台

从 [Releases](https://github.com/orderye/tone-particles/releases) 下载 `tone-particles-0.4.0.zip` 后上传（zip 顶层是 `tone-particles/` 目录，`SKILL.md` 位于该目录内）。不同版本的 Skills 入口位置可能变化，以官方文档为准。

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

运行时以 `SKILL.md` 的「控制指令」一节为准（那才是模型实际读到的口径），本表是同一套指令的速查。

## 配置

本节是配置字段的**单一来源**：其它文档只引用不复制，实际归一逻辑见 `scripts/_core.py` 的 `normalize_config`。

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
    "turns": 3,
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
| `version` | 整数 | 配置 schema 版本，当前为 1；高于支持版本会直接报错 |
| `mode` | `single` / `blend` / `rotate` / `blend_random` | 运行模式 |
| `styles[].id` | `S01`–`S21` | 风格 id；`single` 模式只取第一项 |
| `styles[].weight` | 正整数 | 抽样权重；融合时决定配比 |
| `variants` | `{"S20": "gentle"}` / `{"S20": "strict"}` | 老师子模式；其他风格留空 |
| `density` | `light` / `standard` / `strong` | 密度系数 0.5 / 1 / 1.5 |
| `switch.granularity` | `per_message` / `per_n_turns` / `on_topic_change` / `per_session` | 切换粒度 |
| `switch.no_repeat_window` | 0–10 | 最近 K 条不重复；0 表示允许连续重复 |
| `switch.turns` | 1–20 | `per_n_turns` 时每几条切一次，默认 3 |
| `switch.locked` | 布尔 | 锁定当前风格 |
| `scene_adapt` | 布尔 | 是否按场景自适应降档；危机处理始终生效，不受此开关影响 |
| `kaomoji.enabled` / `level` | 布尔 / `light` / `normal` | 颜文字开关与档位 |
| `emoji` | `style_default` | emoji 使用策略 |
| `paused` | 布尔 | 暂停语气层 |

`config/styles.json` 中每种风格带独立 `version` 与向量，升级时可单独替换某个风格文件而不影响其他风格。`config/particles.json` 是 `check_density.py` 的机器可读词表。

### 配置怎么被写入

所有写入路径（宿主 `update_config()`、MCP `set_user_style`）都走共享核心里同一套「读—改—写」：

- **原子写入**：先写同目录临时文件、flush + fsync，再原子替换。进程在写入中途被杀掉时，旧配置保持完整可读，不会留下半截 JSON。
- **跨进程加锁**：更新期间会持有 `config/user-config.json.lock`。两个进程同时改同一份配置时，后一个会在锁上等待（默认最多 5 秒），拿不到锁就报错，不会静默覆盖。
- **写前校验**：非法值（枚举错、权重非正、风格 id 不存在）直接拒绝，不会写进配置，旧文件字节不变。
- **写后校验**：写完重新读取并归一化，确认落盘数据仍可读。写入失败不会返回「保存成功」。
- **未知字段**：默认保留并向 stderr 告警（不静默丢弃）；严格模式下直接拒绝。
- **越界数值**：`switch.no_repeat_window`（0–10）与 `switch.turns`（1–20）会被夹到合法区间，并产生一条告警——不静默改写用户的意图。
- **权限**：用户配置写为 `0600`（仅本人可读写）。

**多用户隔离**：给每个用户单独的 `config_path` / `history_path`，或用 `TONE_PARTICLES_USER_DIR` 环境变量 / `ToneHost(user_dir=...)` 指定各自的目录。默认路径是 skill 目录下的 `config/`，沿用旧行为。

排查与回滚见 [`Docs/配置升级与故障诊断.md`](Docs/配置升级与故障诊断.md)。

## 接入方式

三种形态**共用同一份 `styles/` 与 `scripts/`**，所以风格提示词在任何一种形态下都完全一致，不会出现「Skill 里是一种腔调、MCP 里是另一种」。

| 形态 | 适合谁 | 代价 |
| --- | --- | --- |
| A. Skill 包 | 已经支持 Skill 的环境 | 随机依赖脚本执行环境 |
| B. 系统提示词注入 | 自研宿主，能改代码 | 需要开发 |
| C. MCP 工具 | 第三方助手生态、现成 MCP 客户端 | 多一次工具调用的延迟 |

**推荐路径**：能在自己宿主里改代码就用 B（最稳，随机由宿主控制）；只能用现成客户端就用 C；直接装 Skill 用 A。

### 系统提示词注入（任意对话应用）

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

### 宿主适配层（Python / 任意语言）

`integrations/` 是可直接参考的完整实现：配置读写、按切换粒度选风格、维护历史、回填回复做密度回检都在里面。

```python
import sys
sys.path.insert(0, "integrations")
from host_adapter import ToneHost

host = ToneHost(config_path="/path/user-config.json",
                 history_path="/path/tone-history.json")
host.begin_session()
turn = host.next_turn("帮我看看这段代码")
system_prompt = base_system_prompt + "\n\n" + turn["system_suffix"]
```

非 Python 宿主用 `integrations/host_cli.py`，每行一个 JSON 请求、一行一个 JSON 响应：

```bash
printf '%s\n' \
  '{"op":"next_turn","user_input":"帮我安排明天的日程","topic":"日程"}' \
| python3 integrations/host_cli.py --config /path/user-config.json --history /path/history.json
```

```bash
python3 integrations/demo_loop.py    # 端到端演示
```

详见 [`Docs/宿主接入指南.md`](Docs/宿主接入指南.md)。

### MCP 工具

MCP 服务（PRD 方案 C）已实现，暴露四个工具：`list_styles`、`get_style_prompt`、`set_user_style`、`pick_next_style`。零依赖，JSON-RPC 2.0 over stdio。

```bash
python3 mcp/server.py --config /path/to/user-config.json
```

注册方式与工具说明见 [`Docs/MCP接入指南.md`](Docs/MCP接入指南.md)。

## 脚本

三个 CLI 脚本都只依赖 Python 标准库（3.9+）。

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

输出包含 `main`、`accents`、`history` 与 `notes`。

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
# 一条命令跑全部自检：四个 config JSON、21 风格完整性、
# md↔json 一致性（密度 / 颜文字倾向 / 签名元素）、版本号一致性、CLI 冒烟、
# 用例结构校验、离线确定性评测、八个测试文件
python3 tools/selfcheck.py

# 端到端评测（确定性指标；需模型的三项标为「未评测」）
python3 eval/run.py

# 严格验收：模型类指标必须真的评测过，否则退出码 2
python3 eval/run.py --strict
```

评测指标分四种状态：**通过 / 未达标 / 未评测 / 被阻塞**。「未评测」是「没跑成」（没有后端、缺回复、评审没作答），「被阻塞」是「评测过程出错」。两者都不是通过，报告里分开统计、分开渲染。详见 [`eval/README.md`](eval/README.md)。

单元测试在 `tests/`（纯标准库，不依赖 pytest），也可以单独跑：

```bash
python3 tests/test_core.py      # 核心函数：配置归一、抽样、轮次状态机
python3 tests/test_host.py      # 宿主适配层（含权重配比回归、状态提交时机）
python3 tests/test_mcp.py       # MCP 协议与四个工具
python3 tests/test_config.py    # 配置读写：原子写、跨进程锁、并发、失败路径
python3 tests/test_protocol.py  # 子进程协议契约：MCP stdio 与宿主 CLI
python3 tests/test_safety.py    # 安全硬规则：文档与用例的一致性回归
python3 tests/test_eval.py      # 评测体系：状态语义、严格模式、报告一致性
python3 tests/test_context.py   # 语境策略与向后兼容的合同测试
```

## 维护与发版

这一节面向维护者，不影响使用者。

### 自检

```bash
python3 tools/selfcheck.py
```

一次跑完：配置可解析、21 个风格文件完整、md↔json 三组字段一致、颜文字库可检出、版本号四处一致、CLI 冒烟、用例结构校验、离线确定性评测、八个测试文件。

### 版本号同步

版本号在四处需要保持一致：`VERSION`（单一来源）、README 的版本行与包名、`mcp/server.py` 的 `SERVER_VERSION`、`config/styles.json` 里 21 个风格的 `version`。

```bash
python3 tools/version.py --set 0.4.0   # 同步四处
python3 tools/version.py --check        # 只校验
```

改完记得手工在下面的「版本」一节补一条变更说明。

### 打包与供应链校验

```bash
python3 tools/package.py            # 构建 dist/tone-particles-<版本>.zip
python3 tools/package.py --check    # 只校验版本串一致性
python3 tools/package.py --verify   # 供应链校验，18 项
```

打包是白名单构建：只含 README、SKILL.md、`config/`、`references/`、`scripts/`、`styles/`，顶层固定 `tone-particles/`，条目排序与固定时间戳保证同样内容产出字节一致的包。

`--verify` 检查：连续两次构建的 SHA-256 是否一致、zip 条目有没有路径穿越 / 绝对路径 / 重复条目、必需文件是否齐全、私有与开发文件（用户配置、历史、锁文件、`eval/`、`tests/`、`tools/`、`dist/`）有没有漏进包里、包内有没有机器路径或密钥形态的内容，以及**解压到临时目录后跑一遍最小使用流程**。通过后会在 `dist/` 里写出内容清单（`tone-particles-<版本>.manifest.json`）与 SHA-256 校验和文件。

### 持续集成

两条流水线跑同一份检查清单（`.github/workflows/eval.yml` 与 `.cnb.yml`）：

- 平台：Linux + macOS；Python：3.9（项目实际最低版本）+ 3.12。**没有 Windows CI，因此不声明 Windows 支持。**
- 检查项：版本一致性 → 配置与 schema 校验 → 自检 → 八个测试文件 → CLI 冒烟 → 离线确定性评测 → 评测报告汇总 → 打包供应链校验。
- 默认流水线**不需要任何密钥、不调用付费模型**。需要模型的评审是独立的 `model-eval` job，只有手动触发（`workflow_dispatch`）并选了非 `none` 的后端才跑，密钥只从 CI secret 读。
- 阻断规则：硬规则、安全红队、配置读写、协议契约、打包完整性任一失败即失败。评测里「未评测」的项**不阻断**普通 CI，但会逐条打印——发布候选验收要用 `python3 eval/run.py --strict`，它会在模型类指标未评测时返回退出码 2。

发版清单见 [`Docs/发布检查清单.md`](Docs/发布检查清单.md)。

## 设计说明与已知限制

- **风格提示词是参考实现**：向量与密度区间来自 PRD 初始设定，`eval/` 的盲测与密度标定就是为校准它们准备的——标定结果出来后应回写 `config/styles.json`。
- **单风格体积**：每个风格文件约 650–900 汉字（含标点与颜文字约 1.1–1.4k 字符），符合 PRD 的 900 字目标——代价是保留了完整的分场景细则、示例与反例。若需进一步压缩，可删去「更多示例」与「反例」两节。
- **随机与权重存在数学取舍**：要求「零连续重复」时，各风格的长期占比无法完全等于设定权重；池子不大于去重窗口时尤其明显。脚本会优先保证不连续重复，并在 `notes` 中说明。若更看重权重精确，把 `no_repeat_window` 设为 0。
- **密度区间是趋势指标**：短回复的每百字密度天然偏高。PRD 附录里的参考示例多为 20–60 字短句，按本工具口径普遍高于标称区间；M4 标定时应以 150–400 字的完整回复重新取样。硬性验收应看「每句 ≤ 1 个主助词」「代码 / 表格内为零」等可判定规则。
- **颜文字依赖字体**：不同平台显示不一致，默认关闭；出现乱码时按 `references/lexicon.md` 退回纯 ASCII。
- **不改变内容**：本 skill 只改表达层，但不能替代事实核查与安全审查。
- **系统提示词注入需要宿主开发**：`compose_prompt.py` 已提供拼装能力，调用时机、历史维护与缓存由宿主负责；`integrations/` 是可直接参考的完整实现。
- **评测的三项指标依赖模型**：风格盲测、内容保真、融合识别需要评审模型；没有配置后端时这三项标为「未评测」，其余指标照常产出。「未评测」既不是通过也不是不达标——发布候选验收请用 `python3 eval/run.py --strict`（模型类指标未评测时返回退出码 2）。
- **提示词不是语义保证**：当前的主要形式是把风格说明加进 system prompt，运行时手上并没有同一条问题的无风格基线回复，因此**运行时做不了真正的双文本语义比对**。评测里的「内容保真」比较的是「原回复」与「剥掉语气后的正文」，验证的是去掉语气不丢信息；「语义锚点保真」守住的是数字、日期、命令、代码、URL 这类关键片段没被改。整段语义等价仍需模型或人工评审，详见 [`eval/README.md`](eval/README.md)。
- **语境判断是文本层面的**：只读本轮输入，不读历史也不读回复。宿主有更准的场景信息时，用 `next_turn(context={...})` 显式指定。

## 安全

风格只是口吻，不是身份或关系。不声明年龄、不扮演未成年人或恋人 / 家人关系位；强势风格不辱骂、不操控；暗黑风格不渲染自伤与暴力；用户出现危机信号时立即关闭风格并给出求助方向。完整规则见 `references/safety.md`，其优先级高于任何风格与配置——配置、宿主元数据、融合权重都不能覆盖它。

## 文档

| 文档 | 内容 |
| --- | --- |
| [`SKILL.md`](SKILL.md) | 模型实际读到的入口：触发条件、每轮流程、硬规则、场景自适应 |
| [`references/safety.md`](references/safety.md) | 安全边界与危机处理（优先级最高） |
| [`references/lexicon.md`](references/lexicon.md) | 助词、标点、颜文字规则 |
| [`references/fusion-rules.md`](references/fusion-rules.md) | 融合、冲突风格、随机与降级 |
| [`references/onboarding.md`](references/onboarding.md) | 导入向导话术与配置写法 |
| [`Docs/宿主接入指南.md`](Docs/宿主接入指南.md) | 宿主接入：调用时机、历史归属、错误处理、配置 schema |
| [`Docs/MCP接入指南.md`](Docs/MCP接入指南.md) | MCP 接入：四个工具、注册方式、错误契约、已知限制 |
| [`Docs/语境策略与场景优先级.md`](Docs/语境策略与场景优先级.md) | 场景优先级表、判定信号、风格向量能力缺口、已知限制 |
| [`Docs/配置升级与故障诊断.md`](Docs/配置升级与故障诊断.md) | 配置版本与迁移、写入语义、故障诊断、不联网的修复流程 |
| [`Docs/发布检查清单.md`](Docs/发布检查清单.md) | 发版前的逐项检查表与回滚步骤 |
| [`Docs/双平台推送流程.md`](Docs/双平台推送流程.md) | GitHub + CNB 双平台推送 SOP、账号隔离模型、SHA 对照 |
| [`Docs/升级执行报告.md`](Docs/升级执行报告.md) | 0.4.0 升级的完整执行报告：基线、逐项改动、测试结果、遗留风险 |
| [`eval/README.md`](eval/README.md) | 评测体系：四种状态、四层指标、后端、判分口径 |
| [`Docs/语气助词 Skill PRD 与部署方案.md`](Docs/语气助词%20Skill%20PRD%20与部署方案.md) | 原始 PRD（历史快照，部分章节已过时） |

## 版本

- `0.4.0`：CI 扩成矩阵（Linux + macOS × Python 3.9 / 3.12）；`tools/package.py` 新增 `--verify` 供应链校验；新增 `tools/version.py` 统一版本号；新增发布检查清单与配置诊断文档。
- `0.3.5`：新增确定性语境策略 `scripts/_context.py`（带 reason code，危机规则不可覆盖）；宿主适配层与 MCP `get_style_prompt` 新增可选 `context` 参数（向后兼容）。
- `0.3.0`：评测引入「通过 / 未达标 / 未评测 / 被阻塞」四种状态与 `--strict` 严格验收开关；报告补上版本、commit、Python 版本、数据哈希与分母定义；新增确定性的「语义锚点保真」指标与用例结构校验。
- `0.2.2`：配置写入改为原子写 + 跨进程锁 + 写前写后校验；MCP 增加 schema 驱动的参数校验；宿主适配层改为「提示词拼装成功后才提交轮次状态」；新增 `user_dir` / `TONE_PARTICLES_USER_DIR` 隔离多用户配置与历史。
- `0.2.1`：修复宿主适配层丢弃配置权重、`--root` 不生效、MCP 静默写入未知配置键三处缺陷；eval 判分不再把「评审未作答 / 回复长度不足」显示成失败。
- `0.2.0`：抽出共享核心 `scripts/_core.py`；新增评测体系（`eval/`）、宿主适配层（`integrations/`）与 MCP 服务（`mcp/`）。
- `0.1.0`：21 风格、四种模式、导入向导、融合 / 随机、场景自适应、颜文字、三个脚本。

逐项改动与测试结果见 [`Docs/升级执行报告.md`](Docs/升级执行报告.md)。
