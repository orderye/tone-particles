"""通用消息式接口后端。

面向「system + messages → content 分块」这一类服务：请求体带 `model` /
`system` / `messages`，响应体在 `content` 数组里返回若干 `{type, text}` 分块。
认证头与版本头都可用环境变量覆盖，以适配不同厂商的字段命名。

只用标准库 urllib，不引入第三方依赖。

环境变量：
    TONE_MSG_BASE_URL       必填，形如 https://<host>
    TONE_MSG_API_KEY        必填
    TONE_MSG_MODEL          必填，模型名由服务端决定
    TONE_MSG_PATH           默认 /v1/messages
    TONE_MSG_AUTH_HEADER    默认 x-api-key
    TONE_MSG_VERSION_HEADER 可选，设置了才发送
    TONE_MSG_VERSION        版本头的取值
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import Backend


class MessagesApiBackend(Backend):
    name = "messages_api"
    can_generate = True

    def __init__(self, base_url=None, api_key=None, model=None, path=None,
                 auth_header=None, version_header=None, version=None):
        self.base_url = (base_url or os.environ.get("TONE_MSG_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("TONE_MSG_API_KEY", "")
        self.model = model or os.environ.get("TONE_MSG_MODEL", "")
        self.path = path or os.environ.get("TONE_MSG_PATH", "/v1/messages")
        self.auth_header = auth_header or os.environ.get("TONE_MSG_AUTH_HEADER", "x-api-key")
        self.version_header = (version_header if version_header is not None
                                else os.environ.get("TONE_MSG_VERSION_HEADER", ""))
        self.version = version if version is not None else os.environ.get("TONE_MSG_VERSION", "")

    def available(self):
        missing = [name for name, value in
                   (("TONE_MSG_BASE_URL", self.base_url),
                    ("TONE_MSG_API_KEY", self.api_key),
                    ("TONE_MSG_MODEL", self.model))
                   if not value]
        if missing:
            return False, "未设置 " + "、".join(missing)
        return True, f"{self.model} @ {self.base_url}"

    def _post(self, path: str, payload: dict) -> dict:
        headers = {
            self.auth_header: self.api_key,
            "Content-Type": "application/json",
        }
        if self.version_header and self.version:
            headers[self.version_header] = self.version
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit(f"模型接口返回 {exc.code}：{detail}")
        except urllib.error.URLError as exc:
            raise SystemExit(f"连不上模型接口 {self.base_url}：{exc.reason}")

    def generate(self, system: str, user: str) -> str:
        data = self._post(self.path, {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0.0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        })
        parts = data.get("content") or []
        return "".join(part.get("text", "") for part in parts if part.get("type") == "text")

    def judge(self, rubric: str, payload: dict) -> dict:
        system = (
            "你是严格、公正的评审员。只依据给定的标准判断，不要输出多余的话。\n"
            "必须只输出一个 JSON 对象，不要加解释性文字或代码围栏。\n\n"
            "评分标准：\n" + rubric
        )
        reply = self.generate(system, json.dumps(payload, ensure_ascii=False, indent=2))
        return self.parse_json_reply(reply)
