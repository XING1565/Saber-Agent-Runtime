from fastapi.testclient import TestClient

from internal.agent.router import route_task
from main import app


def test_chat_route_for_general_message():
    route = route_task("你好，介绍一下你自己")

    assert route.mode == "chat"
    assert route.confidence > 0
    assert "general_chat" in route.signals


def test_rag_route_for_document_question():
    route = route_task("基于上传的项目文档说明 Router 的职责")

    assert route.mode == "rag"
    assert "knowledge_needed" in route.signals
    assert route.selected_tools == ["rag_search"]


def test_tool_route_for_single_tool_intent():
    route = route_task("搜索 Router 相关代码")

    assert route.mode == "tool"
    assert "tool_required" in route.signals
    assert "search_repo" in route.selected_tools


def test_react_route_for_multi_step_engineering_task():
    route = route_task("分析当前项目的 RAG 模块，并生成一份技术说明")

    assert route.mode == "react"
    assert "multi_step" in route.signals
    assert "search_repo" in route.selected_tools
    assert "generate_report" in route.selected_tools


def test_selected_tools_override_default_rules():
    route = route_task("你好", selected_tools=["search_repo", "read_file"])

    assert route.mode == "react"
    assert route.selected_tools == ["search_repo", "read_file"]
    assert "explicit_tools" in route.signals


def test_chat_api_returns_route_and_trace_route():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "运行核心测试并总结失败原因"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "react"
    assert payload["route"]["mode"] == "react"
    assert payload["trace"]["route"] == payload["route"]
    assert payload["trace"]["events"][0]["name"] == "Router"
