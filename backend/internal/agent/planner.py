from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from internal.tools import default_registry

SUPPORTED_TOOLS = default_registry().names()


@dataclass(frozen=True)
class PlanStep:
    id: str
    tool: str
    params: dict[str, Any]
    reason: str
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionPlan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "steps": [step.to_dict() for step in self.steps],
            "validation_errors": list(self.validation_errors),
        }


def build_plan(message: str, route: dict) -> ExecutionPlan:
    query = (message or "").strip()
    mode = str(route.get("mode", "chat"))
    selected_tools = _valid_tools(route.get("selected_tools") or [])
    validation_errors = _tool_errors(route.get("selected_tools") or [])

    if mode == "chat":
        return ExecutionPlan(goal=query or "普通对话", validation_errors=validation_errors)

    if mode == "rag":
        return ExecutionPlan(
            goal=f"基于检索证据回答：{query}",
            steps=[
                PlanStep(
                    id="step_1",
                    tool="rag_search",
                    params={"query": query},
                    reason="先检索相关文档片段，为 Generator 提供证据上下文。",
                    depends_on=[],
                )
            ],
            validation_errors=validation_errors,
        )

    if mode == "tool":
        tool = selected_tools[0] if selected_tools else _fallback_tool(query)
        steps = []
        if tool:
            steps.append(_step_for_tool("step_1", tool, query, []))
        elif not validation_errors:
            validation_errors.append("未匹配到当前 Tool Registry 支持的工具")
        return ExecutionPlan(goal=query, steps=steps, validation_errors=validation_errors)

    tools = selected_tools or _react_tools_for_query(query)
    tools = _dedupe([tool for tool in tools if tool in SUPPORTED_TOOLS])[:4]
    steps = []
    for index, tool in enumerate(tools):
        step_id = f"step_{index + 1}"
        depends_on = [] if index == 0 else [f"step_{index}"]
        steps.append(_step_for_tool(step_id, tool, query, depends_on))
    return ExecutionPlan(goal=query, steps=steps, validation_errors=validation_errors)


def validate_plan(plan: ExecutionPlan) -> list[str]:
    errors = list(plan.validation_errors)
    seen_ids = set()
    for step in plan.steps:
        if not step.id:
            errors.append("plan step id 不能为空")
        if step.id in seen_ids:
            errors.append(f"重复的 plan step id: {step.id}")
        seen_ids.add(step.id)
        if step.tool not in SUPPORTED_TOOLS:
            errors.append(f"非法工具名: {step.tool}")
        for dep in step.depends_on:
            if dep not in seen_ids:
                errors.append(f"{step.id} 依赖不存在或尚未执行的步骤: {dep}")
    return errors


def _valid_tools(tools: list[Any]) -> list[str]:
    return _dedupe([str(tool).strip() for tool in tools if str(tool).strip() in SUPPORTED_TOOLS])


def _tool_errors(tools: list[Any]) -> list[str]:
    return [f"非法工具名: {tool}" for tool in tools if str(tool).strip() and str(tool).strip() not in SUPPORTED_TOOLS]


def _fallback_tool(query: str) -> str:
    lowered = query.lower()
    if "读取文件" in query:
        return "read_file"
    if "运行" in query or "测试" in query:
        return "run_tests"
    if "搜索" in query or "查找" in query or "search" in lowered:
        return "search_repo"
    return ""


def _react_tools_for_query(query: str) -> list[str]:
    tools: list[str] = []
    if "运行" in query or "测试" in query or "失败" in query:
        tools.extend(["run_tests", "generate_report"])
    elif "当前项目" in query or "分析" in query:
        tools.extend(["search_repo", "read_file", "generate_report"])
    elif "总结" in query or "生成报告" in query:
        tools.extend(["search_repo", "generate_report"])
    else:
        tools.extend(["search_repo", "generate_report"])
    return _dedupe(tools)


def _step_for_tool(step_id: str, tool: str, query: str, depends_on: list[str]) -> PlanStep:
    params_by_tool = {
        "search_repo": {"query": _search_query(query), "scope": "."},
        "read_file": {"path": _read_path(query), "lines": 80},
        "rag_search": {"query": query},
        "generate_report": {"title": "Agent Runtime 执行说明", "sections": ["目标", "证据", "结论"]},
        "run_tests": {"target": "core", "flags": "-q"},
    }
    reason_by_tool = {
        "search_repo": "先搜索项目代码或文档，定位与任务相关的文件。",
        "read_file": "读取关键文件内容，为后续总结提供具体依据。",
        "rag_search": "检索知识库片段，并将证据注入上下文。",
        "generate_report": "汇总前序步骤结果，生成结构化说明。",
        "run_tests": "执行核心测试并捕获退出码与错误摘要。",
    }
    return PlanStep(
        id=step_id,
        tool=tool,
        params=params_by_tool.get(tool, {}),
        reason=reason_by_tool.get(tool, "执行 Planner 选择的工具步骤。"),
        depends_on=depends_on,
    )


def _search_query(query: str) -> str:
    if "rag" in query.lower():
        return "rag"
    if "router" in query.lower():
        return "router"
    if "tool" in query.lower():
        return "tool"
    return query


def _read_path(query: str) -> str:
    match = re.search(r"([\w./\\-]+\.(?:py|ts|tsx|md|json|txt))", query)
    if match:
        return match.group(1).replace("\\", "/")
    return "backend/internal/agent/planner.py"


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
