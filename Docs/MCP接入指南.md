# MCP 接入指南

语气助词 Skill 的第三种部署形态（PRD 8.1 的方案 C）：暴露成 MCP 工具，
让支持 MCP 的第三方助手生态也能用上 21 种中文口吻风格。

实现见仓库里的 `mcp/` 目录，零依赖的 JSON-RPC 2.0 over stdio 服务。

---

## 一、三种形态怎么选

| 形态 | 适合谁 | 代价 |
| --- | --- | --- |
| A. Skill 包 | 已经支持 Skill 的环境 | 随机依赖脚本执行环境 |
| B. 系统提示词注入 | 自研宿主，能改代码 | 需要开发 |
| C. MCP 工具 | 第三方助手生态、现成 MCP 客户端 | 多一次工具调用的延迟 |

**推荐路径**：能在自己宿主里改代码就用 B（最稳，随机由宿主控制）；
只能用现成客户端就用 C；直接装 Skill 用 A。

三种形态**共用同一份 `styles/` 与 `scripts/`**，所以风格提示词在任何一种形态下
都完全一致，不会出现「Skill 里是一种腔调、MCP 里是另一种」的情况。

---

## 二、架构

```
第三方助手
   │  MCP over stdio
   ▼
mcp/server.py          JSON-RPC 2.0
   │
   ▼
mcp/tools.py           四个工具
   │
   ▼
scripts/_core.py       核心：配置、风格目录、密度区间、抽样、状态机
scripts/compose_prompt.py
```

工具直接调用核心的纯函数，不走命令行子进程——没有额外进程开销，
也避开了 CLI 层「未知风格 id 静默通过」这类契约缺口。

---

## 三、四个工具的语义

### list_styles

列出 21 个风格，含分组、气质描述、8 维向量、密度区间、颜文字倾向与签名元素。

`include_prompt` 默认关闭：每个风格文件约 1k tokens，21 个一起给会撑爆上下文。
需要某个风格的完整提示词时，用 `get_style_prompt` 单独取。

### get_style_prompt

生成提示词。`style_id` 必填，其余可选：

- `accents`：副风格，最多 2 个。融合总数不超过 3。
- `weights`：与风格一一对应的权重。默认主 4、副 2。
- `density`：`light` / `standard` / `strong`，系数 0.5 / 1 / 1.5。
- `variant`：老师风格（S20）的子模式，`gentle` / `strict`。

返回的 `prompt` 可以直接追加到 system prompt 末尾，与命令行
`compose_prompt.py` 的输出格式完全一致。

### set_user_style

写入用户配置。字段与 PRD 7.4 的 schema 一致，配置文件的完整说明见
[宿主接入指南](宿主接入指南.md#六配置-schema)。

**这个工具会写文件**。多用户环境请给每个用户单独的配置文件路径。

### pick_next_style

按当前配置随机抽一个风格，带去重窗口。`seed` 与 `history` 相同则结果可复现。

**这个工具不持有会话状态**：历史要由调用方自己保存，每轮把最近用过的
风格 id 传进来。命令行版对应的是 `config/tone-history.json`。

---

## 四、为什么历史由调用方持有

MCP 服务是无状态的——它不知道谁在调用、上一次抽到了什么。让调用方持有历史有三个好处：

1. **多用户天然隔离**：每个用户的历史在自己的存储里，不会串。
2. **可回放**：把历史传回去就能复现任意一轮的抽样结果。
3. **服务可以水平扩展**：不需要粘性会话。

代价是调用方要多存一个数组。对大多数宿主来说，这比在服务端维护会话状态更省事。

---

## 五、错误处理

| 情况 | 表现 |
| --- | --- |
| 未知风格 id | `isError: true`，正文是「未知风格 id：S99。可用：S01, …」 |
| `weights` 长度与风格数不一致 | `isError: true` |
| 缺必填参数 | JSON-RPC 错误 `-32602` |
| 未知方法 | JSON-RPC 错误 `-32601` |
| 未知工具 | `isError: true` |
| 配置文件不存在 | 自动回落到 `config/defaults.json`，并在返回里说明 |

工具级错误用 `isError: true` 而不是 JSON-RPC 错误，是因为这类错误模型能读到
并据此自我纠正；协议级错误才用错误码。

---

## 六、安全边界

工具本身不绕过任何安全规则：

- `get_style_prompt` 生成的提示词里，「通用规则」段落永远包含安全边界摘要，
  并指向 `references/safety.md`。
- 场景自适应与危机处理由宿主侧决定（宿主才知道场景），适配层提供密度档位覆盖。
- `set_user_style` 的 `paused` 为 true 时，后续抽取不再注入任何风格。

MCP 工具不代替宿主的安全策略：宿主平台的使用政策优先于本 skill（PRD 第 6 章）。

---

## 七、已知限制

- **不持有会话状态**，见上一节。
- **`set_user_style` 直接写文件**，没有并发写保护。多进程同时写同一份配置
  可能互相覆盖——请给每个用户单独的路径。
- **每次调用都要重新拼装提示词**，没有缓存。风格文件读取有 I/O 开销，
  但相对一次模型调用可以忽略。
- **协议版本固定为 `2024-11-05`**，不实现新版本才有的能力（如 resources 的订阅）。

---

## 八、跑起来看看

```bash
# 自检
python3 mcp/tests/test_mcp.py

# 手动敲一遍协议
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_styles","arguments":{}}}' \
| python3 mcp/server.py
```
