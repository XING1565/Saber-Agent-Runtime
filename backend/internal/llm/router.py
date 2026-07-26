from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from internal.agent.router import RouteDecision, route_task
from internal.tools import default_registry

from .provider import BaseLLMProvider, LLMResult, configured_provider


ROUTE_MODES = {"chat", "rag", "tool", "react"}
SUPPORTED_TOOLS = default_registry().names()


@dataclass(frozen=True)
class RouteGeneration:
    route: dict
    llm: dict[str, Any]


def generate_route(
    message: str,
    use_rag: bool = False,
    selected_tools: list[str] | None = None,
    provider: BaseLLMProvider | None = None,
) -> RouteGeneration:
    fallback_route = route_task(message, use_rag=use_rag, selected_tools=selected_tools).to_dict()
    llm_provider = provider or configured_provider()

    if selected_tools:
        return RouteGeneration(
            route=fallback_route,
            llm=_rule_info(llm_provider, "explicit selected_tools use rule router"),
        )

    if not _enabled():
        return RouteGeneration(route=fallback_route, llm=_rule_info(llm_provider, "LLM_ROUTER_ENABLED is false"))

    result = llm_provider.structured_output(_messages(message, use_rag))
    if result.used_fallback:
        return RouteGeneration(route=fallback_route, llm=_llm_info(result, llm_provider, source="rule"))

    try:
        route = _normalize_route(json.loads(result.content))
    except (TypeError, ValueError) as exc:
        return RouteGeneration(
            route=fallback_route,
            llm=_llm_info(
                LLMResult(
                    content="",
                    provider=result.provider,
                    model=result.model,
                    duration_ms=result.duration_ms,
                    used_fallback=True,
                    error={"code": "invalid_route_output", "message": str(exc)},
                ),
                llm_provider,
                source="rule",
            ),
        )

    return RouteGeneration(route=route.to_dict(), llm=_llm_info(result, llm_provider, source="llm"))


def _enabled() -> bool:
    return os.getenv("LLM_ROUTER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _messages(message: str, use_rag: bool) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是 Saber Agent Runtime 的 Router。只输出 JSON，不要输出 Markdown。"
                "Schema: {\"mode\":\"chat|rag|tool|react\", \"confidence\":0.0-1.0, "
                "\"reason\":\"中文判断依据\", \"signals\":[\"...\"], "
                "\"selected_tools\":[\"search_repo|read_file|rag_search|generate_report|run_tests\"]}."
                "如果任务需要多个步骤或多个工具，mode 使用 react。"
            ),
        },
        {"role": "user", "content": json.dumps({"message": message, "use_rag": use_rag}, ensure_ascii=False)},
    ]


def _normalize_route(payload: dict[str, Any]) -> RouteDecision:
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in ROUTE_MODES:
        raise ValueError(f"非法 route mode: {mode}")

    confidence = payload.get("confidence", 0.7)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = 0.7
    confidence = max(0.0, min(1.0, float(confidence)))

    reason = str(payload.get("reason") or "LLM Router 输出结构化判断。").strip()
    signals = _string_list(payload.get("signals")) or ["llm_route"]
    tools = [tool for tool in _string_list(payload.get("selected_tools")) if tool in SUPPORTED_TOOLS]

    if mode == "rag" and "rag_search" not in tools:
        tools.append("rag_search")

    return RouteDecision(
        mode=mode,
        confidence=confidence,
        reason=reason,
        signals=signals,
        selected_tools=_dedupe(tools),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _rule_info(provider: BaseLLMProvider, reason: str) -> dict[str, Any]:
    return {
        "source": "rule",
        "provider": provider.provider,
        "model": provider.model,
        "enabled": provider.enabled and _enabled(),
        "used_fallback": True,
        "duration_ms": 1,
        "error": {"code": "llm_router_disabled", "message": reason},
    }


def _llm_info(result: LLMResult, provider: BaseLLMProvider, source: str) -> dict[str, Any]:
    info = result.to_dict()
    info["source"] = source
    info["enabled"] = provider.enabled and _enabled()
    return info
