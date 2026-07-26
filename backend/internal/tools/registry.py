from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from internal.rag import DocumentStore, default_document_store


@dataclass(frozen=True)
class ToolParam:
    name: str
    type: str
    description: str
    required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: list[ToolParam]
    function: Callable[[dict[str, Any]], dict[str, Any]]
    timeout: int = 10
    retry_count: int = 0
    risk_level: str = "low"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [param.to_dict() for param in self.parameters],
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "risk_level": self.risk_level,
        }


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: str
    params: dict[str, Any]
    summary: str
    duration_ms: int
    output: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ToolRegistry:
    def __init__(self, tools: list[ToolDefinition]):
        self._tools = {tool.name: tool for tool in tools}

    def names(self) -> set[str]:
        return set(self._tools)

    def list_tools(self) -> list[dict]:
        return [self._tools[name].to_dict() for name in sorted(self._tools)]

    def describe(self, name: str) -> dict | None:
        tool = self._tools.get(name)
        return tool.to_dict() if tool else None

    def policy(self, name: str) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"timeout": 0, "retry_count": 0, "risk_level": "unknown"}
        return {"timeout": tool.timeout, "retry_count": tool.retry_count, "risk_level": tool.risk_level}

    def execute(self, name: str, params: dict[str, Any] | None) -> ToolResult:
        started = perf_counter()
        safe_params = dict(params or {})
        tool = self._tools.get(name)
        if tool is None:
            return self._error(name, safe_params, started, "tool_not_found", f"工具不存在: {name}")

        validation_error = self._validate(tool, safe_params)
        if validation_error:
            return self._error(name, safe_params, started, "invalid_params", validation_error)

        try:
            output = tool.function(safe_params)
            summary = str(output.get("summary") or "工具调用成功")
            return ToolResult(
                tool=name,
                status="success",
                params=safe_params,
                summary=summary,
                duration_ms=_duration(started),
                output=output,
                error=None,
            )
        except Exception as exc:
            return self._error(name, safe_params, started, "execution_error", str(exc))

    def _validate(self, tool: ToolDefinition, params: dict[str, Any]) -> str:
        for param in tool.parameters:
            value = params.get(param.name)
            if param.required and _is_empty(value):
                return f"缺少必填参数: {param.name}"
            if value is not None and value != "" and not _matches_type(value, param.type):
                return f"参数 {param.name} 类型应为 {param.type}"
        return ""

    def _error(self, name: str, params: dict[str, Any], started: float, code: str, message: str) -> ToolResult:
        return ToolResult(
            tool=name,
            status="failed",
            params=params,
            summary=message,
            duration_ms=_duration(started),
            output={},
            error={"code": code, "message": message},
        )


def default_registry(document_store: DocumentStore | None = None) -> ToolRegistry:
    rag_store = document_store or default_document_store()
    return ToolRegistry(
        [
            ToolDefinition(
                name="search_repo",
                description="搜索 Saber Agent Runtime 项目中的代码或文档关键词。",
                parameters=[
                    ToolParam("query", "string", "搜索关键词", True),
                    ToolParam("scope", "string", "限定目录范围", False),
                ],
                function=_search_repo,
                timeout=10,
                retry_count=1,
                risk_level="low",
            ),
            ToolDefinition(
                name="read_file",
                description="读取项目内指定文件或目录的摘要内容。",
                parameters=[
                    ToolParam("path", "string", "项目内相对路径", True),
                    ToolParam("lines", "number", "最多读取行数", False),
                ],
                function=_read_file,
                timeout=10,
                retry_count=0,
                risk_level="medium",
            ),
            ToolDefinition(
                name="rag_search",
                description="在 Mock 文档库中检索相关证据片段。",
                parameters=[ToolParam("query", "string", "问题或检索词", True)],
                function=lambda params: _rag_search(params, rag_store),
                timeout=10,
                retry_count=1,
                risk_level="low",
            ),
            ToolDefinition(
                name="generate_report",
                description="将前序工具结果汇总成 Markdown 技术说明。",
                parameters=[
                    ToolParam("title", "string", "报告标题", True),
                    ToolParam("sections", "array", "报告章节", True),
                ],
                function=_generate_report,
                timeout=10,
                retry_count=0,
                risk_level="low",
            ),
            ToolDefinition(
                name="run_tests",
                description="执行核心测试的演示适配器，返回退出码、耗时和摘要。",
                parameters=[
                    ToolParam("target", "string", "测试目标", False),
                    ToolParam("flags", "string", "测试参数", False),
                ],
                function=_run_tests,
                timeout=30,
                retry_count=1,
                risk_level="medium",
            ),
        ]
    )


def _search_repo(params: dict[str, Any]) -> dict[str, Any]:
    query = str(params.get("query", "")).lower()
    scope = str(params.get("scope") or ".")
    root = _project_root()
    base = _safe_path(root, scope)
    matches = []
    for path in base.rglob("*"):
        if path.is_file() and _is_project_file(path) and query in path.name.lower():
            matches.append(str(path.relative_to(root)).replace("\\", "/"))
        if len(matches) >= 8:
            break
    if not matches:
        matches = _fallback_matches(query)
    return {"summary": f"找到 {len(matches)} 个相关条目", "matches": matches}


def _read_file(params: dict[str, Any]) -> dict[str, Any]:
    root = _project_root()
    target = _safe_path(root, str(params.get("path", "")))
    max_lines = int(params.get("lines") or 80)
    if target.is_dir():
        children = [str(path.relative_to(root)).replace("\\", "/") for path in target.iterdir()][:max_lines]
        return {"summary": f"读取目录 {target.name}，包含 {len(children)} 个条目", "entries": children}
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {params.get('path')}")
    lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()[:max_lines]
    return {"summary": f"读取 {len(lines)} 行内容", "path": str(target.relative_to(root)).replace("\\", "/"), "preview": lines}


def _rag_search(params: dict[str, Any], store: DocumentStore) -> dict[str, Any]:
    query = str(params.get("query", ""))
    top_k = int(params.get("top_k") or 3)
    docs = store.search(query, top_k=top_k)
    return {"summary": f"基于 query 检索到 {len(docs)} 条证据", "query": query, "top_k": top_k, "documents": docs}


def _generate_report(params: dict[str, Any]) -> dict[str, Any]:
    title = str(params.get("title"))
    sections = [str(section) for section in params.get("sections", [])]
    markdown = "\n".join([f"# {title}", "", *[f"## {section}\n- 待 Executor 接入真实上下文后补全。" for section in sections]])
    return {"summary": f"生成 Markdown 报告：{title}", "markdown": markdown}


def _run_tests(params: dict[str, Any]) -> dict[str, Any]:
    target = str(params.get("target") or "core")
    flags = str(params.get("flags") or "-q")
    return {
        "summary": f"测试适配器完成：target={target}, flags={flags}, exit_code=0",
        "exit_code": 0,
        "stdout_summary": "10 passed (mock adapter)",
        "stderr_summary": "",
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError("路径超出项目目录")
    return target


def _is_project_file(path: Path) -> bool:
    ignored = {".pytest_cache", "__pycache__", "node_modules", "dist"}
    return not any(part in ignored for part in path.parts)


def _fallback_matches(query: str) -> list[str]:
    if "rag" in query:
        return ["frontend/src/mockData.ts", "backend/internal/agent/planner.py"]
    if "router" in query:
        return ["backend/internal/agent/router.py", "backend/tests/test_router.py"]
    if "tool" in query:
        return ["backend/internal/tools/registry.py", "frontend/src/mockData.ts"]
    return ["README.md"]


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    return True


def _duration(started: float) -> int:
    return max(1, round((perf_counter() - started) * 1000))
