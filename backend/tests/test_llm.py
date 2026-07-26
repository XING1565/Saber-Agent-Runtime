from fastapi.testclient import TestClient

from internal.llm.provider import BaseLLMProvider, LLMResult
import internal.llm.generator as llm_generator
from main import app


def test_chat_uses_rule_fallback_without_llm_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "解释 Router 为什么这样判断"})

    assert response.status_code == 200
    payload = response.json()
    assert "Router 已将任务路由到" in payload["answer"]
    generator_event = next(event for event in payload["trace"]["events"] if event["name"] == "Generator")
    assert generator_event["status"] == "success"
    assert generator_event["input"]["llm"]["used_fallback"] is True
    assert generator_event["input"]["llm"]["error"]["code"] == "llm_not_configured"


def test_chat_uses_configured_llm_provider_when_available(monkeypatch):
    monkeypatch.setattr(llm_generator, "configured_provider", lambda: _SuccessProvider())
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "总结 Trace 的价值"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "这是来自 mock LLM 的回答。"
    generator_event = next(event for event in payload["trace"]["events"] if event["name"] == "Generator")
    assert generator_event["status"] == "success"
    assert generator_event["input"]["llm"]["provider"] == "openai"
    assert generator_event["input"]["llm"]["used_fallback"] is False


def test_llm_call_failure_falls_back_and_records_trace_warning(monkeypatch):
    monkeypatch.setattr(llm_generator, "configured_provider", lambda: _FailedProvider())
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "生成一份执行说明"})

    assert response.status_code == 200
    payload = response.json()
    assert "Router 已将任务路由到" in payload["answer"]
    generator_event = next(event for event in payload["trace"]["events"] if event["name"] == "Generator")
    assert generator_event["status"] == "warning"
    assert generator_event["error"]["code"] == "llm_call_failed"
    assert generator_event["input"]["llm"]["used_fallback"] is True


def test_structured_output_accepts_valid_json():
    result = _JsonProvider('{"mode":"chat","confidence":0.8}').structured_output([])

    assert result.used_fallback is False
    assert result.error is None


def test_structured_output_rejects_invalid_json():
    result = _JsonProvider("not-json").structured_output([])

    assert result.used_fallback is True
    assert result.error["code"] == "invalid_structured_output"


class _SuccessProvider(BaseLLMProvider):
    provider = "openai"
    default_model = "chat-latest"

    @property
    def enabled(self) -> bool:
        return True

    def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        return LLMResult(
            content="这是来自 mock LLM 的回答。",
            provider=self.provider,
            model=self.model,
            duration_ms=7,
            used_fallback=False,
            error=None,
        )


class _FailedProvider(BaseLLMProvider):
    provider = "deepseek"
    default_model = "deepseek-v4-flash"

    @property
    def enabled(self) -> bool:
        return True

    def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        return LLMResult(
            content="",
            provider=self.provider,
            model=self.model,
            duration_ms=3,
            used_fallback=True,
            error={"code": "llm_call_failed", "message": "mock provider failure"},
        )


class _JsonProvider(_SuccessProvider):
    def __init__(self, content: str):
        super().__init__()
        self._content = content

    def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        return LLMResult(
            content=self._content,
            provider=self.provider,
            model=self.model,
            duration_ms=1,
            used_fallback=False,
            error=None,
        )


def _clear_llm_env(monkeypatch):
    for name in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_TIMEOUT_SECONDS",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
