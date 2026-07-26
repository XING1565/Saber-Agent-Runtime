from fastapi.testclient import TestClient

from internal.agent.planner import SUPPORTED_TOOLS, build_plan, validate_plan
from internal.agent.router import route_task
from main import app


def test_react_plan_has_two_to_four_steps_with_required_fields():
    route = route_task("分析当前项目的 RAG 模块，并生成一份技术说明").to_dict()
    plan = build_plan("分析当前项目的 RAG 模块，并生成一份技术说明", route)

    assert 2 <= len(plan.steps) <= 4
    assert validate_plan(plan) == []
    for step in plan.steps:
        assert step.id
        assert step.tool in SUPPORTED_TOOLS
        assert isinstance(step.params, dict)
        assert step.reason
        assert isinstance(step.depends_on, list)


def test_rag_plan_uses_rag_search():
    route = route_task("基于上传的项目文档说明 Router 的职责").to_dict()
    plan = build_plan("基于上传的项目文档说明 Router 的职责", route)

    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "rag_search"
    assert plan.steps[0].params["query"]


def test_invalid_selected_tool_is_reported_and_excluded():
    route = route_task("你好", selected_tools=["unknown_tool"]).to_dict()
    plan = build_plan("你好", route)
    errors = validate_plan(plan)

    assert "非法工具名: unknown_tool" in errors
    assert all(step.tool != "unknown_tool" for step in plan.steps)


def test_chat_api_returns_plan_and_trace_plan():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "运行核心测试并总结失败原因"})

    assert response.status_code == 200
    payload = response.json()
    assert "plan" in payload
    assert payload["trace"]["plan"] == payload["plan"]
    assert 2 <= len(payload["plan"]["steps"]) <= 4
    assert payload["plan"]["steps"][0]["id"] == "step_1"
    assert payload["trace"]["events"][1]["name"] == "Planner"
