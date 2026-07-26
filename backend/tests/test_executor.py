from dataclasses import dataclass

from fastapi.testclient import TestClient

from internal.executor import execute_plan
from internal.tools import ToolResult
from main import app


def test_invalid_params_does_not_retry_and_stops():
    registry = _FakeRegistry([_failed("invalid_params")], retry_count=3)
    result = execute_plan(_plan("search_repo", {}), registry).tool_calls[0]

    assert result["status"] == "failed"
    assert len(result["attempts"]) == 1
    assert result["recovery"]["summary"] == "failed -> stop"


def test_recoverable_error_retries_and_succeeds():
    registry = _FakeRegistry([_failed("execution_error"), _success()], retry_count=2)
    result = execute_plan(_plan("search_repo", {"query": "router"}), registry).tool_calls[0]

    assert result["status"] == "success"
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["status"] == "failed"
    assert result["attempts"][1]["status"] == "success"
    assert result["recovery"]["summary"] == "failed -> retry -> success"


def test_recoverable_error_exhausts_retry_and_marks_failed():
    registry = _FakeRegistry([_failed("execution_error"), _failed("execution_error")], retry_count=1)
    result = execute_plan(_plan("search_repo", {"query": "router"}), registry).tool_calls[0]

    assert result["status"] == "failed"
    assert len(result["attempts"]) == 2
    assert result["recovery"]["summary"] == "failed -> retry -> stop"


def test_read_file_missing_trace_shows_failed_stop():
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "读取文件 missing.py", "selected_tools": ["read_file"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["trace"]["status"] == "failed"
    tool_call = payload["tool_calls"][0]
    assert tool_call["recovery"]["summary"] == "failed -> stop"
    assert len(tool_call["attempts"]) == 1
    failed_event = next(event for event in payload["trace"]["events"] if event["status"] == "failed")
    assert failed_event["name"] == "Tool Call: read_file"
    assert "failed -> stop" in failed_event["output_summary"]


def _plan(tool: str, params: dict) -> dict:
    return {"steps": [{"id": "step_1", "tool": tool, "params": params}]}


def _success() -> ToolResult:
    return ToolResult(
        tool="search_repo",
        status="success",
        params={"query": "router"},
        summary="工具调用成功",
        duration_ms=1,
        output={"ok": True},
        error=None,
    )


def _failed(code: str) -> ToolResult:
    return ToolResult(
        tool="search_repo",
        status="failed",
        params={"query": "router"},
        summary=f"{code} failure",
        duration_ms=1,
        output={},
        error={"code": code, "message": f"{code} failure"},
    )


@dataclass
class _FakeRegistry:
    results: list[ToolResult]
    retry_count: int

    def policy(self, name: str) -> dict:
        return {"timeout": 10, "retry_count": self.retry_count, "risk_level": "low"}

    def execute(self, name: str, params: dict) -> ToolResult:
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]
