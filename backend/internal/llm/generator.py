from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .provider import BaseLLMProvider, configured_provider


@dataclass(frozen=True)
class AnswerGeneration:
    answer: str
    llm: dict[str, Any]


def generate_answer(
    message: str,
    route: dict,
    plan: dict,
    tool_results: list[dict],
    retrieved_docs: list[dict],
    memory_context: list,
    evidence_chain: dict[str, Any] | None = None,
    provider: BaseLLMProvider | None = None,
) -> AnswerGeneration:
    chain = evidence_chain or _evidence_chain_from_docs(message, retrieved_docs)
    fallback_answer = build_rule_answer(message, route, plan, tool_results, len(retrieved_docs), memory_context, chain)
    llm_provider = provider or configured_provider()
    result = llm_provider.chat(_messages(message, route, plan, tool_results, retrieved_docs, memory_context, chain))
    answer = result.content if result.content and not result.used_fallback else fallback_answer
    llm_info = result.to_dict()
    llm_info["enabled"] = llm_provider.enabled
    return AnswerGeneration(answer=answer, llm=llm_info)


def build_rule_answer(
    message: str,
    route: dict,
    plan: dict,
    tool_results: list[dict],
    retrieved_count: int,
    memory_context: list,
    evidence_chain: dict[str, Any] | None = None,
) -> str:
    mode = route["mode"]
    reason = route["reason"]
    signals = ", ".join(route["signals"])
    step_count = len(plan["steps"])
    tool_count = len(tool_results)
    failed_count = len([result for result in tool_results if result["status"] != "success"])
    memory_count = len(memory_context)
    previous_context = _latest_user_context(memory_context)
    sources = ", ".join((evidence_chain or {}).get("answer_reference", {}).get("sources", [])) or "无"
    return (
        f"Router 已将任务路由到 {mode} 模式。\n"
        f"判断依据：{reason}\n"
        f"命中信号：{signals}\n"
        f"Planner 已生成 {step_count} 个结构化步骤。\n"
        f"Tool Registry 已执行 {tool_count} 次工具调用，失败 {failed_count} 次。\n"
        f"本回答基于 {retrieved_count} 条检索证据和当前 Trace 上下文生成。\n"
        f"已使用的 evidence sources：{sources}。\n"
        f"Memory 注入 {memory_count} 条轻量上下文；最近上下文：{previous_context}\n"
        "当前 Milestone 7 使用轻量 Memory：会话历史、滚动摘要和简单偏好，三层长期记忆留作后续扩展。"
    )


def _messages(
    message: str,
    route: dict,
    plan: dict,
    tool_results: list[dict],
    retrieved_docs: list[dict],
    memory_context: list,
    evidence_chain: dict[str, Any],
) -> list[dict[str, str]]:
    runtime_context = {
        "task": message,
        "route": route,
        "plan": plan,
        "tool_summaries": [
            {
                "tool": result.get("tool"),
                "status": result.get("status"),
                "summary": result.get("summary"),
                "error": result.get("error"),
            }
            for result in tool_results
        ],
        "retrieved_docs": retrieved_docs[:5],
        "evidence_chain": {
            "question": evidence_chain.get("question"),
            "used_context": evidence_chain.get("used_context"),
            "answer_reference": evidence_chain.get("answer_reference"),
        },
        "memory_context": [item.to_dict() if hasattr(item, "to_dict") else item for item in memory_context],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Saber Agent Runtime 的 Generator。请基于 route、plan、工具结果、RAG 证据和 Memory 上下文回答。"
                "回答要简洁、中文为主，并明确说明使用了哪些 evidence source。不要声称执行了未出现在上下文中的真实操作。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(runtime_context, ensure_ascii=False),
        },
    ]


def _latest_user_context(memory_context: list) -> str:
    if not memory_context:
        return "无历史上下文"
    for item in memory_context:
        if getattr(item, "kind", "") == "history":
            user_lines = [line for line in item.content.splitlines() if line.startswith("user: ")]
            if user_lines:
                return user_lines[-1]
    return getattr(memory_context[0], "content", str(memory_context[0]))


def _evidence_chain_from_docs(message: str, retrieved_docs: list[dict]) -> dict[str, Any]:
    chunks = [
        {
            "rank": index + 1,
            "used_by_generator": True,
            "score": doc.get("score", 0),
            "source": doc.get("source", ""),
            "metadata": doc.get("metadata", {}),
            "content": doc.get("content", ""),
        }
        for index, doc in enumerate(retrieved_docs)
    ]
    return {
        "question": message,
        "retrieval_method": "keyword",
        "retrieved_chunks": chunks,
        "used_context": "\n\n".join(f"[{chunk['rank']}] {chunk['source']}: {chunk['content']}" for chunk in chunks),
        "answer_reference": {"used_chunk_count": len(chunks), "sources": [chunk["source"] for chunk in chunks]},
    }
