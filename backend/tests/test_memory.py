from fastapi.testclient import TestClient

from main import app


def test_multi_turn_chat_reads_previous_context():
    client = TestClient(app)
    session_id = "memory-test-session"

    first = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "我的偏好是先给结论，再给步骤。"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "继续说明 Router 为什么这么判断。"},
    )
    payload = second.json()

    assert second.status_code == 200
    assert payload["memory"]
    assert "我的偏好是先给结论" in payload["answer"]


def test_trace_memory_event_explains_context_sources():
    client = TestClient(app)
    session_id = "memory-trace-session"
    client.post("/api/chat", json={"session_id": session_id, "message": "请记住我关注 Trace 展示。"})

    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "这次回答要延续刚才的关注点。"},
    )
    trace = response.json()["trace"]
    memory_event = next(event for event in trace["events"] if event["name"] == "Memory")

    assert memory_event["input"]["session_id"] == session_id
    assert memory_event["input"]["contexts"]
    assert "session_history" in memory_event["output_summary"]
    assert trace["memory"][0]["source"] == "session_history"


def test_memory_api_returns_session_summary_and_preferences():
    client = TestClient(app)
    session_id = "memory-api-session"
    client.post("/api/chat", json={"session_id": session_id, "message": "我希望回答保持简洁。"})

    response = client.get(f"/api/memory/{session_id}")
    payload = response.json()

    assert response.status_code == 200
    assert payload["messages"]
    assert payload["summary"]
    assert payload["preferences"] == ["我希望回答保持简洁。"]
