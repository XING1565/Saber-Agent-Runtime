from fastapi.testclient import TestClient

from main import app


def test_chat_persists_trace_and_trace_api_returns_it():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "分析当前项目的 RAG 模块，并生成一份技术说明"})
    payload = response.json()
    trace_id = payload["trace"]["trace_id"]

    trace_response = client.get(f"/api/traces/{trace_id}")

    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["trace_id"] == trace_id
    assert [event["name"] for event in trace["events"]] == [
        "Router",
        "Planner",
        "Tool Call: search_repo",
        "Tool Call: read_file",
        "Tool Call: generate_report",
        "RAG",
        "Memory",
        "Generator",
        "Answer",
    ]
    assert trace["final_answer"] == payload["answer"]
    assert trace["replay"]["request"]["message"] == "分析当前项目的 RAG 模块，并生成一份技术说明"
    assert trace["runtime_config"]["llm"]["router_source"]


def test_trace_api_returns_404_for_missing_trace():
    client = TestClient(app)

    response = client.get("/api/traces/trace-missing")

    assert response.status_code == 404


def test_trace_replay_api_returns_snapshot_and_404_for_missing_trace():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "运行核心测试并总结失败原因"})
    trace_id = response.json()["trace"]["trace_id"]

    replay_response = client.get(f"/api/traces/{trace_id}/replay")
    missing_response = client.get("/api/traces/trace-missing/replay")

    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert replay["request"]["message"] == "运行核心测试并总结失败原因"
    assert replay["route"]
    assert replay["plan"]
    assert replay["tool_results"]
    assert replay["final_answer"]
    assert missing_response.status_code == 404


def test_trace_compare_api_explains_differences():
    client = TestClient(app)

    left = client.post("/api/chat", json={"message": "搜索 Router 相关代码"}).json()["trace"]["trace_id"]
    right = client.post("/api/chat", json={"message": "基于知识库说明 RAG Trace", "use_rag": True}).json()["trace"]["trace_id"]

    response = client.get(f"/api/traces/compare?left={left}&right={right}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["left"] == left
    assert payload["right"] == right
    assert "route" in payload
    assert "plan" in payload
    assert "tool_calls" in payload
    assert "retrieved_docs" in payload
    assert "latency" in payload
    assert "answer" in payload
    assert "两次执行" in payload["explain"]


def test_trace_compare_returns_404_for_missing_trace():
    client = TestClient(app)

    response = client.get("/api/traces/compare?left=trace-missing-a&right=trace-missing-b")

    assert response.status_code == 404


def test_stream_pushes_trace_events_and_final_answer():
    client = TestClient(app)

    with client.stream("POST", "/api/chat/stream", json={"message": "运行核心测试并总结失败原因"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: trace_event" in body
    assert '"name": "Router"' in body
    assert '"name": "Answer"' in body
    assert "event: final_trace" in body
    assert "event: answer" in body


def test_tool_failure_is_located_in_trace_event():
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "读取文件 missing.py", "selected_tools": ["read_file"]},
    )

    assert response.status_code == 200
    payload = response.json()
    trace = payload["trace"]
    failed_event = next(event for event in trace["events"] if event["status"] == "failed")
    assert trace["status"] == "failed"
    assert failed_event["name"] == "Tool Call: read_file"
    assert failed_event["input"]["params"]["path"] == "missing.py"
    assert failed_event["error"]["code"] == "execution_error"
    assert trace["replay"]["tool_results"][0]["attempts"][0]["error"]["code"] == "execution_error"
    assert trace["replay"]["tool_results"][0]["recovery"]["summary"] == "failed -> stop"
