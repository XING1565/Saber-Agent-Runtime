from fastapi.testclient import TestClient

from internal.rag import sqlite_document_store
from internal.trace import RuntimeTrace, SQLiteTraceStore, TraceEvent
from main import app


def test_health_reports_default_memory_storage():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    storage = response.json()["storage"]
    assert storage["backend"] == "memory"
    assert storage["persistence_enabled"] is False
    assert storage["db_path"] is None


def test_sqlite_trace_store_survives_new_instance(tmp_path):
    db_path = tmp_path / "saber-runtime.db"
    store = SQLiteTraceStore(db_path)
    trace = RuntimeTrace(
        trace_id="trace-sqlite-test",
        task="持久化 Trace",
        status="success",
        route={"mode": "chat", "confidence": 0.8, "reason": "test", "signals": [], "selected_tools": []},
        plan={"goal": "test", "steps": [], "validation_errors": []},
        events=[
            TraceEvent(
                id="route",
                type="route",
                name="Router",
                status="success",
                input={"message": "hello"},
                output_summary="mode=chat",
                duration_ms=1,
            )
        ],
        final_answer="ok",
        replay={"request": {"message": "hello"}, "evidence_chain": {}},
        runtime_config={"storage": {"backend": "sqlite"}},
    )

    store.save(trace)
    restored = SQLiteTraceStore(db_path).get("trace-sqlite-test")

    assert restored is not None
    assert restored.trace_id == trace.trace_id
    assert restored.events[0].name == "Router"
    assert restored.replay["request"]["message"] == "hello"
    assert restored.runtime_config["storage"]["backend"] == "sqlite"


def test_sqlite_document_store_survives_new_instance_and_searches_chunks(tmp_path):
    db_path = tmp_path / "saber-runtime.db"
    store = sqlite_document_store(db_path)
    store.add_document(
        "Persistence Note",
        "Router Planner Trace 可以被持久化。\n\nSQLite 保存上传文档和 chunks。",
        {"source": "upload://persistence.md", "kind": "note"},
    )

    restored = sqlite_document_store(db_path)
    documents = restored.list_documents()
    results = restored.search("SQLite chunks Trace", top_k=5)

    assert any(document["source"] == "upload://persistence.md" for document in documents)
    assert any(result["source"] == "upload://persistence.md" for result in results)
    assert {"content", "source", "score", "metadata"}.issubset(results[0])
