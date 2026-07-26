from fastapi.testclient import TestClient

from internal.tools import default_registry
from main import app


def test_tools_api_lists_core_tools_with_parameter_schema():
    client = TestClient(app)

    response = client.get("/api/tools")

    assert response.status_code == 200
    tools = response.json()
    names = {tool["name"] for tool in tools}
    assert {"search_repo", "read_file", "rag_search", "generate_report", "run_tests"}.issubset(names)
    search_repo = next(tool for tool in tools if tool["name"] == "search_repo")
    assert search_repo["description"]
    assert search_repo["parameters"][0]["name"] == "query"
    assert search_repo["parameters"][0]["required"] is True
    assert search_repo["timeout"] == 10
    assert search_repo["retry_count"] == 1
    assert search_repo["risk_level"] == "low"


def test_tool_validation_returns_structured_error():
    registry = default_registry()

    result = registry.execute("search_repo", {})

    assert result.status == "failed"
    assert result.error == {"code": "invalid_params", "message": "缺少必填参数: query"}
    assert result.duration_ms >= 1


def test_chat_trace_contains_tool_call_params_status_duration_and_summary():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "分析当前项目的 RAG 模块，并生成一份技术说明"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"]
    tool_event = next(event for event in payload["trace"]["events"] if event["type"] == "tool_call")
    assert tool_event["input"]["params"]
    assert tool_event["status"] == "success"
    assert tool_event["duration_ms"] >= 1
    assert tool_event["output_summary"]
    assert payload["tool_calls"][0]["attempts"]
    assert "retry_count" in payload["tool_calls"][0]
    assert "risk_level" in payload["tool_calls"][0]
    assert "recovery" in payload["tool_calls"][0]
