from fastapi.testclient import TestClient

from internal.llm.provider import BaseLLMProvider, LLMResult
import internal.llm.planner as llm_planner
import internal.llm.router as llm_router
from main import app


def test_llm_router_disabled_keeps_rule_route(monkeypatch):
    _clear_llm_env(monkeypatch)
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "搜索 Router 相关代码"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"]["mode"] == "tool"
    router_event = next(event for event in payload["trace"]["events"] if event["name"] == "Router")
    assert router_event["input"]["llm"]["source"] == "rule"
    assert "source=rule" in router_event["output_summary"]


def test_llm_router_uses_valid_structured_route(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_ENABLED", "true")
    monkeypatch.setattr(
        llm_router,
        "configured_provider",
        lambda: _JsonProvider(
            '{"mode":"rag","confidence":0.91,"reason":"需要检索资料回答",'
            '"signals":["rag_requested"],"selected_tools":["rag_search"]}'
        ),
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "说明 Router 文档"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"]["mode"] == "rag"
    assert payload["route"]["selected_tools"] == ["rag_search"]
    router_event = next(event for event in payload["trace"]["events"] if event["name"] == "Router")
    assert router_event["input"]["llm"]["source"] == "llm"
    assert "source=llm" in router_event["output_summary"]


def test_llm_router_invalid_output_falls_back_to_rule(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_ENABLED", "true")
    monkeypatch.setattr(
        llm_router,
        "configured_provider",
        lambda: _JsonProvider('{"mode":"invalid","confidence":2,"selected_tools":["unknown_tool"]}'),
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "搜索 Router 相关代码"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"]["mode"] == "tool"
    assert "search_repo" in payload["route"]["selected_tools"]
    router_event = next(event for event in payload["trace"]["events"] if event["name"] == "Router")
    assert router_event["status"] == "warning"
    assert router_event["error"]["code"] == "invalid_route_output"


def test_llm_planner_uses_valid_plan(monkeypatch):
    monkeypatch.setenv("LLM_PLANNER_ENABLED", "true")
    monkeypatch.setattr(
        llm_planner,
        "configured_provider",
        lambda: _JsonProvider(
            '{"goal":"用 LLM plan 搜索项目","steps":[{"id":"step_1","tool":"search_repo",'
            '"params":{"query":"router","scope":"."},"reason":"定位 Router 代码","depends_on":[]}]}'
        ),
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "分析当前项目 Router"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["goal"] == "用 LLM plan 搜索项目"
    assert payload["plan"]["steps"][0]["tool"] == "search_repo"
    assert payload["plan"]["validation_errors"] == []
    planner_event = next(event for event in payload["trace"]["events"] if event["name"] == "Planner")
    assert planner_event["input"]["llm"]["source"] == "llm"
    assert "source=llm" in planner_event["output_summary"]


def test_llm_planner_reflection_repairs_invalid_tool(monkeypatch):
    monkeypatch.setenv("LLM_PLANNER_ENABLED", "true")
    monkeypatch.setattr(
        llm_planner,
        "configured_provider",
        lambda: _SequenceProvider(
            [
                '{"goal":"bad","steps":[{"id":"step_1","tool":"unknown_tool","params":{},'
                '"reason":"bad","depends_on":[]}]}',
                '{"goal":"fixed","steps":[{"id":"step_1","tool":"search_repo",'
                '"params":{"query":"router","scope":"."},"reason":"修正为合法工具","depends_on":[]}]}',
            ]
        ),
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "分析当前项目 Router"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["goal"] == "fixed"
    assert all(step["tool"] != "unknown_tool" for step in payload["plan"]["steps"])
    planner_event = next(event for event in payload["trace"]["events"] if event["name"] == "Planner")
    assert planner_event["input"]["reflection"]["attempted"] is True
    assert planner_event["input"]["reflection"]["validation_errors"] == []


def test_llm_planner_reflection_failure_falls_back_without_executing_illegal_tool(monkeypatch):
    monkeypatch.setenv("LLM_PLANNER_ENABLED", "true")
    monkeypatch.setattr(
        llm_planner,
        "configured_provider",
        lambda: _SequenceProvider(
            [
                '{"goal":"bad","steps":[{"id":"step_1","tool":"unknown_tool","params":{},'
                '"reason":"bad","depends_on":[]}]}',
                '{"goal":"still bad","steps":[{"id":"step_1","tool":"another_unknown","params":{},'
                '"reason":"bad","depends_on":[]}]}',
            ]
        ),
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "分析当前项目 Router"})

    assert response.status_code == 200
    payload = response.json()
    assert all(call["tool"] != "unknown_tool" for call in payload["tool_calls"])
    assert all(call["tool"] != "another_unknown" for call in payload["tool_calls"])
    assert payload["trace"]["plan"] == payload["plan"]
    planner_event = next(event for event in payload["trace"]["events"] if event["name"] == "Planner")
    assert planner_event["status"] == "warning"
    assert planner_event["error"]["code"] == "plan_reflection_fallback"


class _JsonProvider(BaseLLMProvider):
    provider = "openai"
    default_model = "chat-latest"

    def __init__(self, content: str):
        super().__init__()
        self._content = content

    @property
    def enabled(self) -> bool:
        return True

    def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        return LLMResult(
            content=self._content,
            provider=self.provider,
            model=self.model,
            duration_ms=2,
            used_fallback=False,
            error=None,
        )


class _SequenceProvider(_JsonProvider):
    def __init__(self, contents: list[str]):
        super().__init__(contents[0])
        self._contents = contents
        self._index = 0

    def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        content = self._contents[min(self._index, len(self._contents) - 1)]
        self._index += 1
        return LLMResult(
            content=content,
            provider=self.provider,
            model=self.model,
            duration_ms=2,
            used_fallback=False,
            error=None,
        )


def _clear_llm_env(monkeypatch):
    for name in (
        "LLM_ROUTER_ENABLED",
        "LLM_PLANNER_ENABLED",
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
