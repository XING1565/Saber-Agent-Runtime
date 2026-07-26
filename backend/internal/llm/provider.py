from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, Iterable


@dataclass(frozen=True)
class LLMResult:
    content: str
    provider: str
    model: str
    duration_ms: int
    used_fallback: bool
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class BaseLLMProvider:
    provider = "base"
    default_model = "chat-latest"
    default_base_url: str | None = None
    key_env_names: tuple[str, ...] = ("LLM_API_KEY",)

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model = model or self.default_model
        self.api_key = api_key if api_key is not None else self._env_key()
        self.base_url = base_url if base_url is not None else self.default_base_url
        self.timeout_seconds = timeout_seconds or _timeout_from_env()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        started = perf_counter()
        if not self.enabled:
            return self._fallback(started, "llm_not_configured", f"{self.provider} provider missing API key")
        try:
            client = self._client()
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=self.timeout_seconds,
            )
            content = str(response.choices[0].message.content or "").strip()
            if not content:
                return self._fallback(started, "llm_empty_response", "LLM returned empty content")
            return LLMResult(
                content=content,
                provider=self.provider,
                model=self.model,
                duration_ms=_duration(started),
                used_fallback=False,
                error=None,
            )
        except ImportError as exc:
            return self._fallback(started, "llm_sdk_missing", str(exc))
        except Exception as exc:
            return self._fallback(started, "llm_call_failed", str(exc))

    def stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        result = self.chat(messages)
        if result.content:
            yield result.content

    def structured_output(self, messages: list[dict[str, str]]) -> LLMResult:
        result = self.chat(messages)
        if result.used_fallback:
            return result
        try:
            json.loads(result.content)
            return result
        except json.JSONDecodeError as exc:
            return LLMResult(
                content="",
                provider=result.provider,
                model=result.model,
                duration_ms=result.duration_ms,
                used_fallback=True,
                error={"code": "invalid_structured_output", "message": str(exc)},
            )

    def _client(self):
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)

    def _env_key(self) -> str:
        for name in self.key_env_names:
            value = os.getenv(name)
            if value:
                return value
        return ""

    def _fallback(self, started: float, code: str, message: str) -> LLMResult:
        return LLMResult(
            content="",
            provider=self.provider,
            model=self.model,
            duration_ms=_duration(started),
            used_fallback=True,
            error={"code": code, "message": message},
        )


class FallbackProvider(BaseLLMProvider):
    provider = "fallback"
    default_model = "rule-generator"

    @property
    def enabled(self) -> bool:
        return False

    def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        started = perf_counter()
        return self._fallback(started, "llm_not_configured", "fallback provider uses rule generator")


class OpenAIProvider(BaseLLMProvider):
    provider = "openai"
    default_model = "chat-latest"
    key_env_names = ("LLM_API_KEY", "OPENAI_API_KEY")


class DeepSeekProvider(BaseLLMProvider):
    provider = "deepseek"
    default_model = "deepseek-v4-flash"
    default_base_url = "https://api.deepseek.com"
    key_env_names = ("LLM_API_KEY", "DEEPSEEK_API_KEY")


class QwenProvider(BaseLLMProvider):
    provider = "qwen"
    default_model = "qwen3-coder-plus"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    key_env_names = ("LLM_API_KEY", "DASHSCOPE_API_KEY")


def configured_provider() -> BaseLLMProvider:
    provider_name = os.getenv("LLM_PROVIDER", "fallback").strip().lower()
    model = os.getenv("LLM_MODEL") or None
    api_key = os.getenv("LLM_API_KEY") or None
    base_url = os.getenv("LLM_BASE_URL") or None
    providers = {
        "fallback": FallbackProvider,
        "openai": OpenAIProvider,
        "deepseek": DeepSeekProvider,
        "qwen": QwenProvider,
    }
    provider_cls = providers.get(provider_name, FallbackProvider)
    return provider_cls(model=model, api_key=api_key, base_url=base_url)


def _timeout_from_env() -> float:
    raw = os.getenv("LLM_TIMEOUT_SECONDS", "30")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 30.0


def _duration(started: float) -> int:
    return max(1, round((perf_counter() - started) * 1000))
