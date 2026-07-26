from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


RouteMode = Literal["chat", "rag", "tool", "react"]

_RAG_SIGNALS = ("文档", "知识库", "基于上传", "资料", "rag")
_MULTI_STEP_SIGNALS = ("分析", "总结", "运行", "测试", "失败", "生成报告", "当前项目")
_TOOL_SIGNALS = ("搜索", "查找", "读取文件", "时间", "天气", "执行命令")

_TOOL_BY_SIGNAL = {
    "搜索": "search_repo",
    "查找": "search_repo",
    "读取文件": "read_file",
    "运行": "run_tests",
    "测试": "run_tests",
}


@dataclass(frozen=True)
class RouteDecision:
    mode: RouteMode
    confidence: float
    reason: str
    signals: list[str] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def route_task(message: str, use_rag: bool = False, selected_tools: list[str] | None = None) -> RouteDecision:
    query = (message or "").strip()
    normalized = query.lower()
    explicit_tools = _clean_tools(selected_tools)

    if len(explicit_tools) > 1:
        return RouteDecision(
            mode="react",
            confidence=0.95,
            reason="请求显式选择了多个工具，需要按步骤编排执行。",
            signals=["explicit_tools", "multi_tool", "tool_required"],
            selected_tools=explicit_tools,
        )

    if len(explicit_tools) == 1:
        return RouteDecision(
            mode="tool",
            confidence=0.93,
            reason="请求显式选择了一个工具，适合直接进入单工具调用。",
            signals=["explicit_tool", "tool_required"],
            selected_tools=explicit_tools,
        )

    rag_hits = _hits(normalized, _RAG_SIGNALS)
    if use_rag:
        return RouteDecision(
            mode="rag",
            confidence=0.9,
            reason="任务需要基于文档或知识资料回答，优先检索证据并注入上下文。",
            signals=["rag_requested", "knowledge_needed", *rag_hits],
            selected_tools=["rag_search"],
        )

    multi_hits = _hits(normalized, _MULTI_STEP_SIGNALS)
    if multi_hits:
        tools = _infer_tools(normalized)
        if "当前项目" in query and "search_repo" not in tools:
            tools.insert(0, "search_repo")
        if ("当前项目" in query or "分析" in query) and "read_file" not in tools:
            tools.append("read_file")
        if ("生成报告" in query or "总结" in query or "分析" in query) and "generate_report" not in tools:
            tools.append("generate_report")
        return RouteDecision(
            mode="react",
            confidence=0.88,
            reason="任务包含分析、总结或测试等工程步骤，需要 Router 交给 Planner 和工具链处理。",
            signals=["multi_step", "tool_required", *multi_hits],
            selected_tools=tools,
        )

    if rag_hits:
        return RouteDecision(
            mode="rag",
            confidence=0.86,
            reason="任务需要基于文档或知识资料回答，优先检索证据并注入上下文。",
            signals=["knowledge_needed", *rag_hits],
            selected_tools=["rag_search"],
        )

    tool_hits = _hits(normalized, _TOOL_SIGNALS)
    if tool_hits:
        tools = _infer_tools(normalized)
        return RouteDecision(
            mode="tool",
            confidence=0.84,
            reason="任务命中了明确工具意图，适合直接调用一个工具完成。",
            signals=["tool_required", *tool_hits],
            selected_tools=tools,
        )

    return RouteDecision(
        mode="chat",
        confidence=0.72,
        reason="未命中文档检索、工具调用或多步骤工程任务信号，按普通对话处理。",
        signals=["general_chat"],
        selected_tools=[],
    )


def _hits(normalized_query: str, signals: tuple[str, ...]) -> list[str]:
    return [signal for signal in signals if signal.lower() in normalized_query]


def _clean_tools(selected_tools: list[str] | None) -> list[str]:
    if not selected_tools:
        return []
    cleaned = []
    for tool in selected_tools:
        name = str(tool or "").strip()
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def _infer_tools(normalized_query: str) -> list[str]:
    tools: list[str] = []
    for signal, tool_name in _TOOL_BY_SIGNAL.items():
        if signal.lower() in normalized_query and tool_name not in tools:
            tools.append(tool_name)
    return tools
