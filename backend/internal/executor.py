from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from internal.tools import ToolRegistry


RECOVERABLE_ERRORS = {"execution_error", "timeout"}
STOP_ERRORS = {"invalid_params", "tool_not_found", "permission_denied"}


@dataclass(frozen=True)
class ExecutionResult:
    tool_calls: list[dict[str, Any]]


def execute_plan(plan: dict, registry: ToolRegistry) -> ExecutionResult:
    calls = []
    for step in plan.get("steps", []):
        calls.append(_execute_step(step, registry))
    return ExecutionResult(tool_calls=calls)


def _execute_step(step: dict, registry: ToolRegistry) -> dict[str, Any]:
    tool = str(step.get("tool") or "")
    params = dict(step.get("params") or {})
    policy = registry.policy(tool)
    max_retries = int(policy.get("retry_count") or 0)
    attempts = []

    for attempt_index in range(max_retries + 1):
        result = registry.execute(tool, params).to_dict()
        attempt = {
            "attempt": attempt_index + 1,
            "status": result["status"],
            "params": result["params"],
            "duration_ms": result["duration_ms"],
            "summary": result["summary"],
            "error": result["error"],
        }
        attempts.append(attempt)

        if result["status"] == "success":
            return _final_call(step, result, policy, attempts, _recovery("success", attempts))

        error_code = ((result.get("error") or {}).get("code") or "").strip()
        if not _should_retry(error_code, attempt_index, max_retries):
            return _final_call(step, result, policy, attempts, _recovery("stop", attempts, error_code))

    return _final_call(step, result, policy, attempts, _recovery("stop", attempts, "retry_exhausted"))


def _should_retry(error_code: str, attempt_index: int, max_retries: int) -> bool:
    return error_code in RECOVERABLE_ERRORS and error_code not in STOP_ERRORS and attempt_index < max_retries


def _final_call(step: dict, result: dict, policy: dict, attempts: list[dict], recovery: dict) -> dict[str, Any]:
    final = dict(result)
    final["step_id"] = step["id"]
    final["attempts"] = attempts
    final["retry_count"] = int(policy.get("retry_count") or 0)
    final["risk_level"] = str(policy.get("risk_level") or "unknown")
    final["timeout"] = int(policy.get("timeout") or 0)
    final["recovery"] = recovery
    return final


def _recovery(status: str, attempts: list[dict], error_code: str = "") -> dict:
    if status == "success" and len(attempts) > 1:
        return {"status": "recovered", "strategy": "retry", "summary": "failed -> retry -> success"}
    if status == "success":
        return {"status": "none", "strategy": "none", "summary": "success"}
    if error_code in RECOVERABLE_ERRORS and len(attempts) > 1:
        return {"status": "failed", "strategy": "retry_exhausted", "summary": "failed -> retry -> stop"}
    return {"status": "stopped", "strategy": "stop", "summary": "failed -> stop"}
