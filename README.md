# Saber Agent Runtime

> 面向复杂任务的可观测 Agent Runtime Workbench，用 Trace 解释 Agent 为什么这样路由、规划、调用工具、检索证据、注入记忆并生成回答。

Saber Agent Runtime 不是普通 Chatbot，也不是企业级知识库平台。它聚焦一次 Agent 执行过程本身：让 Router、Planner、Executor、Tool Calling、RAG、Memory、Generator 和 Trace 都能被观察、调试和复盘。

```text
User -> Router -> Planner -> Executor -> Tools / RAG / Memory -> Generator -> Trace
```

## Demo

![Saber Agent Runtime Demo](./saber-agent-runtime-demo.gif)

## 项目简介

这个项目用于展示一个轻量但完整的 Agent Runtime 调试闭环：

- Router 输出结构化路由：`mode / confidence / reason / signals / selected_tools`
- Planner 输出稳定 JSON Plan：`goal / steps / validation_errors`
- Executor 调用 Tool Registry，并记录失败、重试和恢复信息
- RAG 返回 Top-K 证据片段，并形成 Evidence Chain
- Memory 注入轻量会话历史、摘要和简单偏好
- Trace 记录每个阶段的 input、output、latency、reason 和 error
- 前端 Workbench 可以在一屏观察 route、plan、tool calls、evidence、memory 和 answer

适合用于：

- AI Agent / 大模型应用开发实习项目展示
- Agent Runtime 架构讲解
- Tool Calling 和 Trace 调试演示
- RAG 证据链展示
- 多轮会话上下文演示

## 演示素材

当前项目支持本地运行演示。建议后续补充以下截图到 `docs/`：

```text
docs/
├── workbench.png        # Agent Debug Workbench 第一屏
├── trace-detail.png     # Trace Detail / Replay / Compare
├── rag-evidence.png     # RAG Evidence Explorer
├── tool-calls.png       # Tool Calls 与失败定位
└── memory-context.png   # Memory Context
```

## 功能展示

- [x] Agent Debug Workbench
- [x] 结构化 Router：`chat / rag / tool / react`
- [x] Router 判断依据：`confidence / reason / signals`
- [x] Planner JSON Plan
- [x] Tool Registry：`search_repo / read_file / rag_search / generate_report / run_tests`
- [x] Executor retry / error recovery Trace
- [x] RAG 文档上传和关键词检索
- [x] Evidence Chain：`question -> retrieved chunks -> used context -> answer`
- [x] Trace Timeline / Detail / Replay / Compare
- [x] 轻量 Session Memory
- [x] 前后端真实 `/api/chat` 联调
- [x] Mock fallback
- [x] 可选 SQLite 本地持久化 Trace 和 Document
- [ ] PostgreSQL 持久化适配
- [ ] Redis Session 缓存和执行状态
- [ ] Docker 本地一键启动
- [ ] 更完整的评测样本管理

## 技术栈

| Category | Tech |
| --- | --- |
| Frontend | React 18 + Vite + TypeScript |
| Backend | FastAPI + Pydantic |
| Runtime | Router / Planner / Executor / Generator |
| Tooling | Tool Registry |
| RAG | DocumentStore + keyword scoring |
| Memory | in-memory MemoryStore |
| Trace | RuntimeTrace + TraceStore + SSE |
| Optional Persistence | SQLite |
| Test | pytest / Vite build |
| Dev Server | Uvicorn / Vite |

默认使用进程内存储，便于本地演示。配置 `STORAGE_BACKEND=sqlite` 后，Trace 和上传文档会写入 SQLite 文件，服务重启后可继续查询。Memory 当前仍为轻量进程内实现。

## 系统架构

```text
User
  |
  v
React + Vite Workbench
  |
  v
FastAPI
  |
  v
Router -> Planner -> Executor -> Generator
              |
              v
      Tool Registry
      - search_repo
      - read_file
      - rag_search
      - generate_report
      - run_tests
              |
              v
       RAG / Memory / Trace
              |
              v
     Memory Store / Trace Store / Document Store
              |
              v
      memory 或 optional SQLite
```

## Agent Workflow

```text
1. 用户提交任务
2. Router 判断任务模式，并输出 reason 和 signals
3. Planner 生成 JSON Plan
4. Executor 按步骤调用 Tool Registry
5. RAG 检索 Top-K 证据片段并构造 Evidence Chain
6. Memory 注入轻量会话上下文
7. Generator 基于工具结果、检索证据和记忆生成回答
8. Trace 记录完整执行链路
```

一次复杂任务的 Trace 会包含：

```text
Router
Planner
Tool Call
RAG
Memory
Generator
Answer
```

## 项目结构

```text
Saber Agent Runtime/
├── README.md
├── docs/
│   └── pro-roadmap.md
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── internal/
│   │   ├── agent/
│   │   ├── executor.py
│   │   ├── llm/
│   │   ├── memory/
│   │   ├── rag/
│   │   ├── tools/
│   │   └── trace/
│   └── tests/
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
```

## 快速开始

### 启动后端

```bash
cd backend
F:\development\anaconda3\python.exe -m pip install -r requirements.txt
F:\development\anaconda3\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

健康检查：

```text
http://127.0.0.1:8000/health
```

### 启动前端

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5178
```

访问：

```text
http://127.0.0.1:5178
```

## 配置说明

### 前端

```bash
VITE_API_BASE_URL=http://localhost:8000
```

### 后端 LLM Provider

不配置 Key 时，系统使用规则 fallback，演示仍可稳定运行。

```bash
LLM_PROVIDER=openai|deepseek|qwen|fallback
LLM_MODEL=<model-name>
LLM_API_KEY=<key>
LLM_BASE_URL=<optional-compatible-endpoint>
LLM_TIMEOUT_SECONDS=30
LLM_ROUTER_ENABLED=false
LLM_PLANNER_ENABLED=false
```

### 可选 SQLite 持久化

默认：

```bash
STORAGE_BACKEND=memory
```

开启本地 SQLite：

```bash
cd backend
$env:STORAGE_BACKEND="sqlite"
$env:SQLITE_DB_PATH="./data/saber-runtime.db"
F:\development\anaconda3\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

开启后：

- `TraceStore` 会持久化完整 Trace JSON
- `DocumentStore` 会持久化上传文档和 chunks
- `/api/traces/{trace_id}`、`/api/traces/{trace_id}/replay`、`rag_search` 在服务重启后仍可使用已保存数据
- `MemoryStore` 当前仍为进程内轻量会话记忆

## API 文档

| Method | Endpoint | 说明 |
| --- | --- | --- |
| GET | `/health` | 服务状态与 storage 配置摘要 |
| POST | `/api/chat` | 执行一次 Agent 任务 |
| POST | `/api/chat/stream` | SSE 推送 Trace events |
| GET | `/api/tools` | 列出 Tool Registry |
| GET | `/api/documents` | 列出文档库 |
| POST | `/api/documents` | 上传文本类文档 |
| GET | `/api/traces/{trace_id}` | 查询完整 Trace |
| GET | `/api/traces/{trace_id}/replay` | 查询 Replay 快照 |
| GET | `/api/traces/compare` | 对比两次 Trace |
| GET | `/api/memory/{session_id}` | 查询轻量会话记忆 |

## 核心实现

### 为什么不是普通 Chatbot

普通 Chatbot 只展示输入和回答。Saber 展示回答背后的执行过程：为什么进入某个 route、Planner 生成了哪些步骤、工具调用是否成功、RAG 证据如何进入 Generator、Memory 注入了哪些上下文。

### Trace 如何解释 Agent 为什么这么做

Trace 中每个 event 都包含：

- `input`
- `output_summary`
- `duration_ms`
- `status`
- `error`

当工具失败时，可以从 Tool Call event 看到 params、attempts、recovery 和 error code。

### RAG Evidence Chain

RAG 不只返回答案，还展示：

```text
question -> retrieved chunks -> score -> used context -> answer
```

当前使用关键词评分，不接 Embedding、Vector Search 或 Rerank，保证本地演示稳定。

### Memory 当前存什么

当前 Memory 只保留：

- 最近会话历史
- 必要历史摘要
- 简单显式偏好

复杂长期记忆、三层记忆和跨会话画像属于后续增强。

## 测试

后端：

```bash
cd backend
F:\development\anaconda3\python.exe -m pytest -q
```

前端：

```bash
cd frontend
npm run build
```

文档风险词检查可按需拆分执行，避免把检查命令本身计入匹配结果：

```bash
rg -n "PostgreSQL|Redis|Docker" README.md docs/pro-roadmap.md
```

检查结果应只出现在“后续增强 / 可选部署”语境中。

## 当前指标

| Metric | Current |
| --- | --- |
| 后端测试 | pytest 覆盖 Router、Planner、Tool、RAG、Memory、Trace、Persistence |
| 前端构建 | Vite production build |
| 默认存储 | in-memory |
| 可选持久化 | SQLite for Trace / Document |
| RAG 检索 | keyword scoring |

## Roadmap

- [x] Milestone 1：项目叙事收敛
- [x] Milestone 2：Router 结构化
- [x] Milestone 3：Planner 标准化
- [x] Milestone 4：Tool Registry 强化
- [x] Milestone 5：Trace 闭环
- [x] Milestone 6：RAG 证据展示
- [x] Milestone 7：Memory 轻量收敛
- [x] Milestone 8：前后端真实联调
- [x] Milestone 9：LLM Provider Layer
- [x] Milestone 10：LLM Router & Planner 可选增强
- [x] Milestone 11：Executor Retry & Error Recovery
- [x] Milestone 12：Trace Detail / Replay / Compare
- [x] Milestone 13：RAG Evidence Explorer
- [x] Milestone 14：Agent Debug Workbench UI
- [x] Milestone 15：SQLite Persistence Optional Polish

后续可选增强：

- PostgreSQL：替换 SQLite，持久化 Trace、Document、Evaluation 样本
- Redis：Session 缓存和轻量执行状态
- Docker：本地一键启动
- Evaluation Center：沉淀测试样本和回归评测结果

## 部署说明

当前项目以本地演示为主：

- 后端：FastAPI + Uvicorn
- 前端：Vite dev server
- 默认存储：进程内
- 可选本地持久化：SQLite

Docker、PostgreSQL、Redis 不是当前默认能力，后续可作为部署增强补充。

## FAQ

**Q：服务重启后数据会保留吗？**

默认不会。开启 `STORAGE_BACKEND=sqlite` 后，Trace 和上传文档会保存在 `SQLITE_DB_PATH` 指向的 SQLite 文件中。

**Q：现在接入真实 LLM 了吗？**

Generator 可以在配置 Key 后使用 LLM Provider；Router 和 Planner 默认仍使用规则 fallback，只有显式开启 `LLM_ROUTER_ENABLED` 或 `LLM_PLANNER_ENABLED` 才会尝试模型结构化输出。

**Q：RAG 是向量检索吗？**

不是。当前使用确定性关键词评分，重点是展示证据链和 Trace 可观测性。

**Q：这是平台类产品吗？**

不是。Saber 保持 Agent Runtime / Agent Debug Workbench 定位，不做组织权限、租户隔离或平台化工作流系统。

## License

MIT

## Contact

请将以下信息替换为你的个人联系方式：

- GitHub: `https://github.com/your-name`
- Email: `your-email@example.com`
