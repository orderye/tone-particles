# 宿主接入包

语气助词 Skill 的宿主侧接入实现（PRD 8.1 方案 B：系统提示词注入）。

| 文件 | 用途 |
| --- | --- |
| `tone_core/` | 把 skill 的核心能力包成稳定的 Python API。核心实现只有一份（skill 目录下的 `scripts/_core.py`），这里只做转发 |
| `host_adapter.py` | 参考宿主适配器：读配置 → 按切换粒度选风格 → 拼提示词 → 维护历史 → 写回配置 |
| `host_cli.py` | 同一套能力的 JSON over stdio 版本，给 Node / Go / Rust 等非 Python 宿主 |
| `demo_loop.py` | 可跑的端到端演示，用假模型验证链路 |

完整说明见 [`Docs/宿主接入指南.md`](../Docs/宿主接入指南.md)。

## 快速上手

```python
import sys
sys.path.insert(0, "integrations")
from host_adapter import ToneHost

host = ToneHost(
    config_path="/var/lib/myapp/users/u42/user-config.json",
    history_path="/var/lib/myapp/users/u42/tone-history.json",
)
host.begin_session()

turn = host.next_turn(user_input, topic=topic)
if turn["active"]:
    system_prompt = base_system_prompt + "\n\n" + turn["system_suffix"]

# 模型回复之后（可选）
check = host.observe(reply)
```

## 依赖

只需要 Python 3.9+ 与标准库。没有第三方依赖，`tone_core/` 也不引入任何包。

## 不进 skill 分发包

`integrations/` 与 `mcp/` 是给宿主开发者的，不随 skill 的 zip 分发——
用户把 skill 装进自己的 skills 目录时不需要这些文件。
