from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceEvent:
    id: str
    type: str
    name: str
    status: str
    input: dict[str, Any]
    output_summary: str
    duration_ms: int
    error: dict[str, Any] | str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceEvent":
        return cls(
            id=str(payload["id"]),
            type=str(payload["type"]),
            name=str(payload["name"]),
            status=str(payload["status"]),
            input=dict(payload.get("input") or {}),
            output_summary=str(payload.get("output_summary") or ""),
            duration_ms=int(payload.get("duration_ms") or 0),
            error=payload.get("error"),
        )


@dataclass(frozen=True)
class RuntimeTrace:
    trace_id: str
    task: str
    status: str
    route: dict[str, Any]
    plan: dict[str, Any]
    events: list[TraceEvent] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    retrieved_docs: list[dict[str, Any]] = field(default_factory=list)
    evidence_chain: dict[str, Any] = field(default_factory=dict)
    memory: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    total_duration_ms: int = 0
    replay: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: _now_iso())
    completed_at: str | None = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "task": self.task,
            "status": self.status,
            "route": self.route,
            "plan": self.plan,
            "events": [event.to_dict() for event in self.events],
            "tool_calls": self.tool_calls,
            "retrieved_docs": self.retrieved_docs,
            "evidence_chain": self.evidence_chain,
            "memory": self.memory,
            "final_answer": self.final_answer,
            "total_duration_ms": self.total_duration_ms,
            "replay": self.replay,
            "runtime_config": self.runtime_config,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeTrace":
        return cls(
            trace_id=str(payload["trace_id"]),
            task=str(payload.get("task") or ""),
            status=str(payload.get("status") or "success"),
            route=dict(payload.get("route") or {}),
            plan=dict(payload.get("plan") or {}),
            events=[TraceEvent.from_dict(event) for event in payload.get("events") or []],
            tool_calls=list(payload.get("tool_calls") or []),
            retrieved_docs=list(payload.get("retrieved_docs") or []),
            evidence_chain=dict(payload.get("evidence_chain") or {}),
            memory=list(payload.get("memory") or []),
            final_answer=str(payload.get("final_answer") or ""),
            total_duration_ms=int(payload.get("total_duration_ms") or 0),
            replay=dict(payload.get("replay") or {}),
            runtime_config=dict(payload.get("runtime_config") or {}),
            started_at=str(payload.get("started_at") or _now_iso()),
            completed_at=payload.get("completed_at"),
        )


class TraceStore:
    def __init__(self) -> None:
        self._traces: dict[str, RuntimeTrace] = {}

    def save(self, trace: RuntimeTrace) -> RuntimeTrace:
        self._traces[trace.trace_id] = trace
        return trace

    def get(self, trace_id: str) -> RuntimeTrace | None:
        return self._traces.get(trace_id)

    def compare(self, left_id: str, right_id: str) -> dict[str, Any] | None:
        left = self.get(left_id)
        right = self.get(right_id)
        if left is None or right is None:
            return None
        return compare_traces(left, right)


class SQLiteTraceStore(TraceStore):
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        super().__init__()
        self._load_traces()

    def save(self, trace: RuntimeTrace) -> RuntimeTrace:
        super().save(trace)
        payload = json.dumps(trace.to_dict(), ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO traces (trace_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (trace.trace_id, payload, trace.started_at, _now_iso()),
            )
        return trace

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _load_traces(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT payload FROM traces").fetchall()
        for (payload,) in rows:
            trace = RuntimeTrace.from_dict(json.loads(payload))
            self._traces[trace.trace_id] = trace


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compare_traces(left: RuntimeTrace, right: RuntimeTrace) -> dict[str, Any]:
    left_dict = left.to_dict()
    right_dict = right.to_dict()
    route_diff = {
        "mode_changed": left.route.get("mode") != right.route.get("mode"),
        "confidence_delta": round(float(right.route.get("confidence", 0)) - float(left.route.get("confidence", 0)), 3),
        "reason_changed": left.route.get("reason") != right.route.get("reason"),
    }
    left_tools = [step.get("tool") for step in left.plan.get("steps", [])]
    right_tools = [step.get("tool") for step in right.plan.get("steps", [])]
    left_sources = [doc.get("source") for doc in left.retrieved_docs]
    right_sources = [doc.get("source") for doc in right.retrieved_docs]
    answer_diff = _first_line(left.final_answer) != _first_line(right.final_answer)
    result = {
        "left": left.trace_id,
        "right": right.trace_id,
        "route": route_diff,
        "plan": {
            "step_count_delta": len(right.plan.get("steps", [])) - len(left.plan.get("steps", [])),
            "tools_changed": left_tools != right_tools,
            "left_tools": left_tools,
            "right_tools": right_tools,
        },
        "tool_calls": {
            "count_delta": len(right.tool_calls) - len(left.tool_calls),
            "status_changed": [call.get("status") for call in left.tool_calls] != [call.get("status") for call in right.tool_calls],
        },
        "retrieved_docs": {
            "count_delta": len(right.retrieved_docs) - len(left.retrieved_docs),
            "sources_changed": left_sources != right_sources,
            "left_sources": left_sources,
            "right_sources": right_sources,
        },
        "latency": {"delta_ms": right.total_duration_ms - left.total_duration_ms},
        "answer": {
            "first_line_changed": answer_diff,
            "left_first_line": _first_line(left.final_answer),
            "right_first_line": _first_line(right.final_answer),
        },
        "explain": _explain_compare(left_dict, right_dict, route_diff, left_tools, right_tools, left_sources, right_sources),
    }
    return result


def _first_line(text: str) -> str:
    return (text or "").splitlines()[0] if text else ""


def _explain_compare(
    left: dict[str, Any],
    right: dict[str, Any],
    route_diff: dict[str, Any],
    left_tools: list[str],
    right_tools: list[str],
    left_sources: list[str],
    right_sources: list[str],
) -> str:
    reasons = []
    if route_diff["mode_changed"]:
        reasons.append("路由模式不同")
    if left_tools != right_tools:
        reasons.append("Planner 选择的工具链不同")
    if [call.get("status") for call in left.get("tool_calls", [])] != [call.get("status") for call in right.get("tool_calls", [])]:
        reasons.append("工具调用状态不同")
    if left_sources != right_sources:
        reasons.append("RAG 检索证据来源不同")
    if right.get("total_duration_ms") != left.get("total_duration_ms"):
        reasons.append("执行耗时不同")
    if not reasons:
        return "两次执行的核心链路基本一致，差异主要来自 trace_id、时间戳或回答细节。"
    return "两次执行不同主要因为：" + "、".join(reasons) + "。"
