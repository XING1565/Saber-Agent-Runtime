from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from internal.agent.planner import ExecutionPlan, PlanStep, build_plan, validate_plan
from internal.tools import default_registry

from .provider import BaseLLMProvider, LLMResult, configured_provider


SUPPORTED_TOOLS = default_registry().names()


@dataclass(frozen=True)
class PlanGeneration:
    plan: dict
    validation_errors: list[str]
    llm: dict[str, Any]
    reflection: dict[str, Any]


def generate_plan(
    message: str,
    route: dict,
    provider: BaseLLMProvider | None = None,
) -> PlanGeneration:
    fallback = build_plan(message, route)
    fallback_errors = validate_plan(fallback)
    llm_provider = provider or configured_provider()

    if not _enabled():
        return _generation(fallback, fallback_errors, _rule_info(llm_provider, "LLM_PLANNER_ENABLED is false"), _no_reflection())

    result = llm_provider.structured_output(_messages(message, route))
    plan = _plan_from_result(result)
    if plan is not None:
        errors = validate_plan(plan)
        if not errors:
            return _generation(plan, errors, _llm_info(result, llm_provider, "llm"), _no_reflection())

        reflection = _reflect_plan(llm_provider, message, route, plan, errors)
        if reflection["plan"] is not None and not reflection["validation_errors"]:
            return _generation(
                reflection["plan"],
                [],
                _llm_info(result, llm_provider, "llm"),
                reflection["info"],
            )
        return _generation(
            fallback,
            fallback_errors,
            _llm_info(result, llm_provider, "rule"),
            reflection["info"],
        )

    return _generation(fallback, fallback_errors, _llm_info(result, llm_provider, "rule"), _no_reflection())


def _reflect_plan(
    provider: BaseLLMProvider,
    message: str,
    route: dict,
    invalid_plan: ExecutionPlan,
    errors: list[str],
) -> dict[str, Any]:
    result = provider.structured_output(_reflection_messages(message, route, invalid_plan.to_dict(), errors))
    plan = _plan_from_result(result)
    validation_errors = validate_plan(plan) if plan is not None else ["reflection did not return a valid plan"]
    info = _llm_info(result, provider, "llm" if plan is not None and not validation_errors else "rule")
    info["attempted"] = True
    info["input_errors"] = errors
    info["validation_errors"] = validation_errors
    return {"plan": plan, "validation_errors": validation_errors, "info": info}


def _plan_from_result(result: LLMResult) -> ExecutionPlan | None:
    if result.used_fallback:
        return None
    try:
        return _normalize_plan(json.loads(result.content))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _normalize_plan(payload: dict[str, Any]) -> ExecutionPlan:
    goal = str(payload.get("goal") or "执行用户任务").strip()
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("plan.steps must be a list")

    steps = []
    for index, raw_step in enumerate(raw_steps[:4]):
        if not isinstance(raw_step, dict):
            raise ValueError("plan step must be an object")
        step_id = str(raw_step.get("id") or f"step_{index + 1}").strip()
        tool = str(raw_step.get("tool") or "").strip()
        params = raw_step.get("params") if isinstance(raw_step.get("params"), dict) else {}
        reason = str(raw_step.get("reason") or "LLM Planner 选择该步骤。").strip()
        depends_on = _string_list(raw_step.get("depends_on"))
        steps.append(PlanStep(id=step_id, tool=tool, params=params, reason=reason, depends_on=depends_on))

    return ExecutionPlan(goal=goal, steps=steps, validation_errors=[])


def _enabled() -> bool:
    return os.getenv("LLM_PLANNER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _messages(message: str, route: dict) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是 Saber Agent Runtime 的 Planner。只输出 JSON，不要输出 Markdown。"
                "Schema: {\"goal\":\"...\", \"steps\":[{\"id\":\"step_1\", "
                "\"tool\":\"search_repo|read_file|rag_search|generate_report|run_tests\", "
                "\"params\":{}, \"reason\":\"中文原因\", \"depends_on\":[]}]}."
                "最多输出 4 步；chat 模式可以输出空 steps。只能使用给定工具名。"
            ),
        },
        {"role": "user", "content": json.dumps({"message": message, "route": route}, ensure_ascii=False)},
    ]


def _reflection_messages(message: str, route: dict, plan: dict, errors: list[str]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是 Saber Agent Runtime 的 Plan Validator。修正 plan，使它只使用合法工具、合法依赖，"
                "并保持同一 JSON Schema。只输出修正后的 JSON。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"message": message, "route": route, "invalid_plan": plan, "validation_errors": errors},
                ensure_ascii=False,
            ),
        },
    ]


def _generation(plan: ExecutionPlan, errors: list[str], llm: dict[str, Any], reflection: dict[str, Any]) -> PlanGeneration:
    plan_dict = plan.to_dict()
    plan_dict["validation_errors"] = errors
    return PlanGeneration(plan=plan_dict, validation_errors=errors, llm=llm, reflection=reflection)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _rule_info(provider: BaseLLMProvider, reason: str) -> dict[str, Any]:
    return {
        "source": "rule",
        "provider": provider.provider,
        "model": provider.model,
        "enabled": provider.enabled and _enabled(),
        "used_fallback": True,
        "duration_ms": 1,
        "error": {"code": "llm_planner_disabled", "message": reason},
    }


def _llm_info(result: LLMResult, provider: BaseLLMProvider, source: str) -> dict[str, Any]:
    info = result.to_dict()
    info["source"] = source
    info["enabled"] = provider.enabled and _enabled()
    return info


def _no_reflection() -> dict[str, Any]:
    return {"attempted": False, "validation_errors": []}
