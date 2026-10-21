"""通用对话补全后端。

任何提供 `/chat/completions` 的服务都能用（各家云端接口、本地推理服务、
自建网关等）。只用标准库 urllib，不引入第三方依赖。

环境变量：
    TONE_CHAT_BASE_URL      必填，形如 https://<host>/v1
    TONE_CHAT_API_KEY       必填
    TONE_CHAT_MODEL         必填，模型名由服务端决定
    TONE_CHAT_TEMPERATURE   默认 0
    TONE_CHAT_AUTH_HEADER   默认 Authorization
    TONE_CHAT_AUTH_PREFIX   默认 "Bearer "
    TONE_CHAT_TIMEOUT       单次请求超时秒数，默认 120
    TONE_CHAT_RETRIES       网络 / 5xx 的重试上限，默认 0（不重试）
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import Backend

DEFAULT_TIMEOUT = 120.0
DEFAULT_RETRIES = 0


class ChatCompletionsBackend(Backend):
    name = "chat_completions"
    can_generate = True

    def __init__(self, base_url=None, api_key=None, model=None, temperature=None,
                 auth_header=None, auth_prefix=None, timeout=None, retries=None):
        self.base_url = (base_url or os.environ.get("TONE_CHAT_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("TONE_CHAT_API_KEY", "")
        self.model = model or os.environ.get("TONE_CHAT_MODEL", "")
        raw = temperature if temperature is not None else os.environ.get("TONE_CHAT_TEMPERATURE", "0")
        self.temperature = float(raw)
        self.auth_header = auth_header or os.environ.get("TONE_CHAT_AUTH_HEADER", "Authorization")
        self.auth_prefix = (auth_prefix if auth_prefix is not None
                            else os.environ.get("TONE_CHAT_AUTH_PREFIX", "Bearer "))
        raw_timeout = timeout if timeout is not None else os.environ.get(
            "TONE_CHAT_TIMEOUT", DEFAULT_TIMEOUT)
        self.timeout = float(raw_timeout)
        raw_retries = retries if retries is not None else os.environ.get(
            "TONE_CHAT_RETRIES", DEFAULT_RETRIES)
        self.retries = max(0, int(raw_retries))

    def available(self):
        missing = [name for name, value in
                   (("TONE_CHAT_BASE_URL", self.base_url),
                    ("TONE_CHAT_API_KEY", self.api_key),
                    ("TONE_CHAT_MODEL", self.model))
                   if not value]
        if missing:
            return False, "未设置 " + "、".join(missing)
        return True, f"{self.model} @ {self.base_url}"

    def metadata(self) -> dict:
        return {
            "后端": self.name,
            "模型": self.model or "unknown",
            "接口": self.base_url or "unknown",
            "温度": self.temperature,
            "超时（秒）": self.timeout,
            "重试上限": self.retries,
        }

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                self.auth_header: f"{self.auth_prefix}{self.api_key}",
                "Content-Type": "application/json",
            },
        )
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                # 4xx 是请求本身的问题，重试没有意义；5xx 才值得重试。
                if exc.code < 500 or attempt >= self.retries:
                    raise SystemExit(f"模型接口返回 {exc.code}：{detail}")
                last_error = f"HTTP {exc.code}：{detail}"
            except urllib.error.URLError as exc:
                if attempt >= self.retries:
                    raise SystemExit(f"连不上模型接口 {self.base_url}：{exc.reason}")
                last_error = str(exc.reason)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"模型接口返回的不是合法 JSON：{exc}")
            if attempt < self.retries:
                time.sleep(min(2 ** attempt, 5))
        raise SystemExit(f"模型接口请求失败：{last_error}")

    def generate(self, system: str, user: str) -> str:
        data = self._post("/chat/completions", {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        })
        choices = data.get("choices") or []
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")

    def judge(self, rubric: str, payload: dict) -> dict:
        system = (
            "你是严格、公正的评审员。只依据给定的标准判断，不要输出多余的话。\n"
            "必须只输出一个 JSON 对象，不要加解释性文字或代码围栏。\n\n"
            "评分标准：\n" + rubric
        )
        reply = self.generate(system, json.dumps(payload, ensure_ascii=False, indent=2))
        return self.parse_json_reply(reply)
