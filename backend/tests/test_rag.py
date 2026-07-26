from fastapi.testclient import TestClient

from main import app


def test_uploaded_document_can_be_retrieved_by_rag_search():
    client = TestClient(app)

    upload = client.post(
        "/api/documents",
        json={
            "title": "Trace 面试说明",
            "content": "Router 负责选择模式。\n\nPlanner 生成步骤。Trace 展示 retrieved chunks 和证据来源。",
            "metadata": {"source": "upload://trace-interview.md", "kind": "interview-note"},
        },
    )

    assert upload.status_code == 200
    assert upload.json()["chunk_count"] == 2

    response = client.post("/api/chat", json={"message": "基于资料说明 Router Planner Trace", "use_rag": True})

    assert response.status_code == 200
    payload = response.json()
    docs = payload["trace"]["retrieved_docs"]
    assert docs
    assert {"content", "source", "score", "metadata"}.issubset(docs[0])
    assert any(doc["source"] == "upload://trace-interview.md" for doc in docs)
    chain = payload["trace"]["evidence_chain"]
    assert chain["question"] == "基于资料说明 Router Planner Trace"
    assert chain["retrieval_method"] == "keyword"
    assert chain["retrieved_chunks"]
    assert {"rank", "score", "source", "metadata", "content", "used_by_generator"}.issubset(chain["retrieved_chunks"][0])
    assert chain["retrieved_chunks"][0]["used_by_generator"] is True
    assert chain["used_context"]


def test_rag_trace_event_records_retrieved_chunks_and_sources():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "基于知识库说明 RAG Trace", "use_rag": True})

    assert response.status_code == 200
    payload = response.json()
    rag_event = next(event for event in payload["trace"]["events"] if event["name"] == "RAG")
    assert rag_event["input"]["retrieved_docs"]
    assert rag_event["input"]["sources"]
    assert rag_event["input"]["evidence_chain"]["used_context"]
    assert "used context" in rag_event["output_summary"]
    generator_event = next(event for event in payload["trace"]["events"] if event["name"] == "Generator")
    assert generator_event["input"]["evidence_chain"]["used_chunk_count"] >= 1
    assert "本回答基于" in payload["answer"]
    assert "检索证据" in payload["answer"]
    assert "已使用的 evidence sources" in payload["answer"]


def test_replay_contains_evidence_chain():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "基于知识库说明 RAG Trace", "use_rag": True})
    trace = response.json()["trace"]

    assert trace["replay"]["evidence_chain"] == trace["evidence_chain"]


def test_evidence_chain_is_stable_without_retrieved_docs():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "你好，普通对话"})

    assert response.status_code == 200
    chain = response.json()["trace"]["evidence_chain"]
    assert chain["question"] == "你好，普通对话"
    assert chain["retrieval_method"] == "keyword"
    assert chain["retrieved_chunks"] == []
    assert chain["used_context"] == ""
