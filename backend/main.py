from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from internal.executor import execute_plan
from internal.llm import generate_answer, generate_plan, generate_route
from internal.memory import MemoryStore
from internal.rag import default_document_store, sqlite_document_store
from internal.trace import RuntimeTrace, SQLiteTraceStore, TraceEvent, TraceStore
from internal.tools import default_registry


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = "default"
    use_rag: bool = False
    selected_tools: list[str] | None = None


class DocumentRequest(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    metadata: dict | None = None


app = FastAPI(title="Saber Agent Runtime", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
logger = logging.getLogger("saber-agent-runtime")


def _storage_backend() -> str:
    backend = os.getenv("STORAGE_BACKEND", "memory").strip().lower()
    if backend not in {"memory", "sqlite"}:
        raise RuntimeError("STORAGE_BACKEND must be 'memory' or 'sqlite'")
    return backend


def _sqlite_db_path() -> str:
    return os.getenv("SQLITE_DB_PATH", "./data/saber-runtime.db")


def _build_document_store():
    if _storage_backend() == "sqlite":
        return sqlite_document_store(_sqlite_db_path())
    return default_document_store()


def _build_trace_store():
    if _storage_backend() == "sqlite":
        return SQLiteTraceStore(_sqlite_db_path())
    return TraceStore()


document_store = _build_document_store()
tool_registry = default_registry(document_store)
trace_store = _build_trace_store()
memory_store = MemoryStore()


def _log_runtime_config() -> None:
    logger.info(
        "Saber Agent Runtime config: storage=%s sqlite_path=%s llm_provider=%s router_enabled=%s planner_enabled=%s",
        _storage_backend(),
        _sqlite_db_path() if _storage_backend() == "sqlite" else "",
        os.getenv("LLM_PROVIDER", "fallback"),
        os.getenv("LLM_ROUTER_ENABLED", "false"),
        os.getenv("LLM_PLANNER_ENABLED", "false"),
    )


_log_runtime_config()


@app.get("/health")
def health() -> dict:
    backend = _storage_backend()
    return {
        "status": "ok",
        "service": "saber-agent-runtime",
        "storage": {
            "backend": backend,
            "db_path": _sqlite_db_path() if backend == "sqlite" else None,
            "persistence_enabled": backend == "sqlite",
        },
    }


@app.get("/api/tools")
def tools() -> list[dict]:
    return tool_registry.list_tools()


@app.get("/api/documents")
def documents() -> list[dict]:
    return document_store.list_documents()


@app.post("/api/documents")
def upload_document(req: DocumentRequest) -> dict:
    record = document_store.add_document(req.title, req.content, req.metadata or {})
    return record.to_dict()


@app.get("/api/memory/{session_id}")
def get_memory(session_id: str) -> dict:
    return memory_store.get_session(session_id)


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    return _run_chat(req)


@app.get("/api/traces/compare")
def compare_trace(left: str, right: str) -> dict:
    result = trace_store.compare(left, right)
    if result is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return result


@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str) -> dict:
    trace = trace_store.get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace.to_dict()


@app.get("/api/traces/{trace_id}/replay")
def get_trace_replay(trace_id: str) -> dict:
    trace = trace_store.get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace.replay


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    payload = _run_chat(req)
    trace = payload["trace"]

    def event_stream():
        for event in trace["events"]:
            yield _sse("trace_event", event)
        yield _sse("final_trace", trace)
        yield _sse("answer", {"trace_id": trace["trace_id"], "answer": payload["answer"]})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _run_chat(req: ChatRequest) -> dict:
    started = perf_counter()
    memory_context = memory_store.context_for(req.session_id)
    route_generation = generate_route(req.message, use_rag=req.use_rag, selected_tools=req.selected_tools)
    route = route_generation.route
    plan_generation = generate_plan(req.message, route)
    plan = plan_generation.plan
    plan_errors = plan_generation.validation_errors
    tool_results = execute_plan(plan, tool_registry).tool_calls
    duration_ms = max(1, round((perf_counter() - started) * 1000))
    retrieved_docs = _retrieved_docs_from_tools(tool_results)
    evidence_chain = _build_evidence_chain(_rag_query_from_tools(tool_results) or req.message, retrieved_docs)
    generation = generate_answer(req.message, route, plan, tool_results, retrieved_docs, memory_context, evidence_chain)
    answer = generation.answer
    memory_store.append_turn(req.session_id, req.message, answer)
    trace = _build_trace(
        req,
        route,
        plan,
        plan_errors,
        tool_results,
        answer,
        duration_ms,
        memory_context,
        generation.llm,
        evidence_chain,
        route_generation.llm,
        plan_generation.llm,
        plan_generation.reflection,
    )
    trace_store.save(trace)
    return {
        "answer": answer,
        "mode": route["mode"],
        "route": route,
        "plan": plan,
        "tool_calls": tool_results,
        "trace": trace.to_dict(),
        "memory": [item.to_dict() for item in memory_context],
        "success": trace.status != "failed",
    }


def _tool_events(result: dict) -> list[TraceEvent]:
    attempts = result.get("attempts") or [
        {
            "attempt": 1,
            "status": result["status"],
            "params": result["params"],
            "duration_ms": result["duration_ms"],
            "summary": result["summary"],
            "error": result["error"],
        }
    ]
    events = []
    for attempt in attempts:
        attempt_no = int(attempt.get("attempt") or 1)
        is_single_attempt = len(attempts) == 1
        status = "success" if attempt.get("status") == "success" else "failed"
        suffix = "" if is_single_attempt else f" (attempt {attempt_no} {status})"
        recovery = result.get("recovery") or {}
        summary = str(attempt.get("summary") or result["summary"])
        if attempt_no == len(attempts) and recovery.get("summary") and recovery.get("summary") != "success":
            summary = f"{summary} · {recovery['summary']}"
        events.append(
            TraceEvent(
                id=f"{result['step_id']}-tool-attempt-{attempt_no}",
                type="tool_call",
                name=f"Tool Call: {result['tool']}{suffix}",
                status=status,
                input={
                    "params": attempt.get("params") or result["params"],
                    "step_id": result["step_id"],
                    "attempt": attempt_no,
                    "retry_count": result.get("retry_count", 0),
                    "risk_level": result.get("risk_level", "unknown"),
                    "recovery": recovery,
                },
                output_summary=summary,
                duration_ms=int(attempt.get("duration_ms") or 1),
                error=attempt.get("error"),
            )
        )
    return events


def _build_trace(
    req: ChatRequest,
    route: dict,
    plan: dict,
    plan_errors: list[str],
    tool_results: list[dict],
    answer: str,
    router_duration_ms: int,
    memory_context: list,
    llm_info: dict,
    evidence_chain: dict,
    route_llm: dict,
    plan_llm: dict,
    plan_reflection: dict,
) -> RuntimeTrace:
    trace_id = f"trace-{uuid4().hex[:12]}"
    retrieved_docs = _retrieved_docs_from_tools(tool_results)
    memory_items = [item.to_dict() for item in memory_context]
    events = [
        TraceEvent(
            id="route",
            type="route",
            name="Router",
            status=_llm_stage_status(route_llm),
            input={
                "message": req.message,
                "use_rag": req.use_rag,
                "selected_tools": req.selected_tools or [],
                "llm": route_llm,
            },
            output_summary=(
                f"source={route_llm.get('source', 'rule')}, "
                f"mode={route['mode']}, confidence={route['confidence']}, "
                f"reason={route['reason']}"
            ),
            duration_ms=int(route_llm.get("duration_ms") or router_duration_ms),
            error=_llm_stage_error(route_llm),
        ),
        TraceEvent(
            id="plan",
            type="plan",
            name="Planner",
            status=_planner_status(plan_errors, plan_llm, plan_reflection),
            input={
                "mode": route["mode"],
                "selected_tools": route["selected_tools"],
                "llm": plan_llm,
                "reflection": plan_reflection,
            },
            output_summary=(
                f"source={plan_llm.get('source', 'rule')}, "
                f"reflection={'yes' if plan_reflection.get('attempted') else 'no'}, "
                f"generated {len(plan['steps'])} steps"
            ),
            duration_ms=int(plan_llm.get("duration_ms") or 1) + int(plan_reflection.get("duration_ms") or 0),
            error=_planner_error(plan_errors, plan_llm, plan_reflection),
        ),
        *[event for result in tool_results for event in _tool_events(result)],
        TraceEvent(
            id="rag",
            type="rag",
            name="RAG",
            status="success",
            input={
                "query": _rag_query_from_tools(tool_results) or req.message,
                "top_k": len(retrieved_docs),
                "sources": [doc["source"] for doc in retrieved_docs],
                "retrieved_docs": retrieved_docs,
                "evidence_chain": evidence_chain,
            },
            output_summary=f"question -> {len(retrieved_docs)} retrieved chunks -> used context",
            duration_ms=1,
            error=None,
        ),
        TraceEvent(
            id="memory",
            type="memory",
            name="Memory",
            status="success",
            input={"session_id": req.session_id, "task": req.message, "contexts": memory_items},
            output_summary=_memory_summary(memory_items),
            duration_ms=1,
            error=None,
        ),
        TraceEvent(
            id="generator",
            type="generator",
            name="Generator",
            status=_generator_status(llm_info),
            input={
                "route_mode": route["mode"],
                "tool_call_count": len(tool_results),
                "retrieved_docs": len(retrieved_docs),
                "evidence_chain": _evidence_chain_summary(evidence_chain),
                "llm": llm_info,
            },
            output_summary=_generator_summary(llm_info),
            duration_ms=int(llm_info.get("duration_ms") or 1),
            error=_generator_error(llm_info),
        ),
        TraceEvent(
            id="answer",
            type="answer",
            name="Answer",
            status="success",
            input={"trace_id": trace_id},
            output_summary=answer.splitlines()[0] if answer else "生成最终回答",
            duration_ms=1,
            error=None,
        ),
    ]
    failed_tool = any(result["status"] != "success" for result in tool_results)
    total_duration_ms = router_duration_ms + sum(event.duration_ms for event in events[1:])
    return RuntimeTrace(
        trace_id=trace_id,
        task=req.message,
        status="failed" if failed_tool else "success",
        route=route,
        plan=plan,
        events=events,
        tool_calls=tool_results,
        retrieved_docs=retrieved_docs,
        evidence_chain=evidence_chain,
        memory=memory_items,
        final_answer=answer,
        total_duration_ms=total_duration_ms,
        replay=_build_replay(req, route, plan, tool_results, retrieved_docs, evidence_chain, memory_items, answer),
        runtime_config=_runtime_config(route_llm, plan_llm, llm_info, tool_results),
    )


def _retrieved_docs_from_tools(tool_results: list[dict]) -> list[dict]:
    docs: list[dict] = []
    for result in tool_results:
        output = result.get("output") or {}
        for doc in output.get("documents") or []:
            docs.append(doc)
    return docs


def _rag_query_from_tools(tool_results: list[dict]) -> str:
    for result in tool_results:
        if result.get("tool") == "rag_search":
            return str((result.get("output") or {}).get("query") or result.get("params", {}).get("query") or "")
    return ""


def _build_evidence_chain(question: str, retrieved_docs: list[dict]) -> dict:
    chunks = []
    for index, doc in enumerate(retrieved_docs):
        chunks.append(
            {
                "rank": index + 1,
                "used_by_generator": True,
                "score": doc.get("score", 0),
                "source": doc.get("source", ""),
                "metadata": doc.get("metadata", {}),
                "content": doc.get("content", ""),
            }
        )
    used_context = "\n\n".join(f"[{chunk['rank']}] {chunk['source']}: {chunk['content']}" for chunk in chunks)
    return {
        "question": question,
        "retrieval_method": "keyword",
        "retrieved_chunks": chunks,
        "used_context": used_context,
        "answer_reference": {
            "used_chunk_count": len(chunks),
            "sources": [chunk["source"] for chunk in chunks],
            "summary": f"Generator 使用 {len(chunks)} 条 keyword 检索证据生成回答。",
        },
    }


def _evidence_chain_summary(evidence_chain: dict) -> dict:
    reference = evidence_chain.get("answer_reference") or {}
    return {
        "retrieval_method": evidence_chain.get("retrieval_method", "keyword"),
        "used_chunk_count": reference.get("used_chunk_count", 0),
        "sources": reference.get("sources", []),
        "used_context_length": len(evidence_chain.get("used_context") or ""),
    }


def _memory_summary(memory_items: list[dict]) -> str:
    if not memory_items:
        return "本轮未注入历史上下文，仅记录当前输入"
    sources = ", ".join(item["source"] for item in memory_items)
    return f"注入 {len(memory_items)} 条轻量上下文：{sources}"


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _generator_status(llm_info: dict) -> str:
    error = llm_info.get("error") or {}
    if error and error.get("code") != "llm_not_configured":
        return "warning"
    return "success"


def _generator_summary(llm_info: dict) -> str:
    provider = llm_info.get("provider", "fallback")
    model = llm_info.get("model", "rule-generator")
    if llm_info.get("used_fallback"):
        return f"LLM provider={provider}, model={model} 使用规则 fallback 生成回答"
    return f"LLM provider={provider}, model={model} 基于检索上下文、工具结果和轻量记忆生成回答"


def _generator_error(llm_info: dict) -> dict | None:
    error = llm_info.get("error")
    if error and error.get("code") != "llm_not_configured":
        return error
    return None


def _llm_stage_status(info: dict) -> str:
    error = info.get("error") or {}
    if error and error.get("code") not in {"llm_router_disabled", "llm_planner_disabled", "llm_not_configured"}:
        return "warning"
    return "success"


def _llm_stage_error(info: dict) -> dict | None:
    error = info.get("error")
    if error and error.get("code") not in {"llm_router_disabled", "llm_planner_disabled", "llm_not_configured"}:
        return error
    return None


def _planner_status(plan_errors: list[str], plan_llm: dict, reflection: dict) -> str:
    if plan_errors:
        return "warning"
    if _llm_stage_error(plan_llm):
        return "warning"
    if reflection.get("attempted") and reflection.get("validation_errors"):
        return "warning"
    return "success"


def _planner_error(plan_errors: list[str], plan_llm: dict, reflection: dict) -> dict | None:
    if plan_errors:
        return {"code": "plan_validation_warning", "message": "; ".join(plan_errors)}
    if reflection.get("attempted") and reflection.get("validation_errors"):
        return {
            "code": "plan_reflection_fallback",
            "message": "; ".join(reflection.get("validation_errors") or []),
        }
    return _llm_stage_error(plan_llm)


def _build_replay(
    req: ChatRequest,
    route: dict,
    plan: dict,
    tool_results: list[dict],
    retrieved_docs: list[dict],
    evidence_chain: dict,
    memory_items: list[dict],
    answer: str,
) -> dict:
    return {
        "request": req.model_dump(),
        "route": route,
        "plan": plan,
        "tool_results": [
            {
                "step_id": result.get("step_id"),
                "tool": result.get("tool"),
                "status": result.get("status"),
                "summary": result.get("summary"),
                "error": result.get("error"),
                "attempts": result.get("attempts", []),
                "recovery": result.get("recovery"),
            }
            for result in tool_results
        ],
        "retrieved_docs": retrieved_docs,
        "evidence_chain": evidence_chain,
        "memory": memory_items,
        "final_answer": answer,
    }


def _runtime_config(route_llm: dict, plan_llm: dict, generator_llm: dict, tool_results: list[dict]) -> dict:
    backend = _storage_backend()
    return {
        "storage": {
            "backend": backend,
            "db_path": _sqlite_db_path() if backend == "sqlite" else None,
            "persistence_enabled": backend == "sqlite",
            "memory_persistence": "in_memory",
        },
        "llm": {
            "provider": os.getenv("LLM_PROVIDER", "fallback"),
            "router_enabled": os.getenv("LLM_ROUTER_ENABLED", "false"),
            "planner_enabled": os.getenv("LLM_PLANNER_ENABLED", "false"),
            "router_source": route_llm.get("source", "rule"),
            "planner_source": plan_llm.get("source", "rule"),
            "generator_provider": generator_llm.get("provider", "fallback"),
            "generator_model": generator_llm.get("model", "rule-generator"),
            "generator_used_fallback": generator_llm.get("used_fallback", True),
        },
        "tool_retry": [
            {
                "tool": result.get("tool"),
                "retry_count": result.get("retry_count", 0),
                "risk_level": result.get("risk_level", "unknown"),
                "recovery": result.get("recovery"),
            }
            for result in tool_results
        ],
    }
