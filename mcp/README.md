# 语气助词 Skill · MCP 服务

把语气助词 Skill 暴露成 MCP 工具（PRD 8.1 的方案 C），让支持 MCP 的第三方
助手生态也能用上 21 种中文口吻风格。

**零依赖**：JSON-RPC 2.0 over stdio，纯标准库实现，不需要 pip install 任何东西。

## 四个工具

| 工具 | 作用 | 关键入参 |
| --- | --- | --- |
| `list_styles` | 列出 21 个风格 | `group?`、`include_prompt?` |
| `get_style_prompt` | 生成单一或融合风格的提示词 | `style_id`、`accents?`、`weights?`、`density?`、`variant?` |
| `set_user_style` | 写入用户的语气偏好 | `mode?`、`styles?`、`density?`、`switch?`、`kaomoji?`、`paused?` |
| `pick_next_style` | 按当前配置抽取本轮风格 | `history?`、`seed?` |

## 跑起来

```bash
python3 mcp/server.py --config /path/to/user-config.json
```

自检：

```bash
python3 tests/test_mcp.py
```

## 注册到客户端

写进客户端的 MCP 配置文件（不同平台的路径与字段名以各自文档为准，
下面以通用的 `mcpServers` 字段为例）：

```json
{
  "mcpServers": {
    "tone-particles": {
      "command": "python3",
      "args": [
        "/绝对路径/mcp/server.py",
        "--config",
        "/绝对路径/config/user-config.json"
      ]
    }
  }
}
```

用 `绝对路径` 而不是相对路径——MCP 服务由宿主启动，工作目录不一定是你的项目目录。

## 典型用法

```
用户：帮我用傲娇的语气回一句

助手 → list_styles()
        确认 S09 傲娇的 id 与词库

助手 → set_user_style({"mode": "single", "styles": [{"id": "S09", "weight": 1}]})

助手 → get_style_prompt({"style_id": "S09"})
        拿到 prompt，把它追加到 system prompt 末尾

助手 → pick_next_style({"seed": 7})
        确认这一轮用的是哪个风格
```

随机模式下更常见的顺序是 `pick_next_style()` 先抽，再 `get_style_prompt()` 拼。

## 输出格式

四个工具都返回 JSON 文本（放在 MCP 的 `content[].text` 里），字段与命令行
`compose_prompt.py --json` 的输出保持一致，便于两边对照。

## 协议细节

- 传输：stdio，每行一条 JSON-RPC 2.0 消息。
- 协议版本：`2024-11-05`。
- 支持的方法：`initialize`、`notifications/initialized`、`tools/list`、`tools/call`、
  `ping`、`resources/list`（空）、`prompts/list`（空）。
- 工具级错误（未知风格 id、参数长度不匹配）以 `isError: true` 返回；
  协议级错误（未知方法、缺必填参数）用 JSON-RPC 错误码。

## 边界

- MCP 服务**不持有会话状态**。历史由调用方通过 `pick_next_style` 的 `history`
  参数传入并自行保存（对应命令行里的 `config/tone-history.json`）。
- `set_user_style` 会**直接写文件**。多用户环境请给每个用户单独的 `--config` 路径。
- 不进 skill 分发包：用户把 skill 装进自己的 skills 目录时不需要 MCP 服务，
  它是给宿主开发者的。

更完整的说明见 [`Docs/MCP接入指南.md`](../Docs/MCP接入指南.md)。
