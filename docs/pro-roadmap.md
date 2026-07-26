# Saber Agent Runtime Enhancement Roadmap

> 升级方向：保持 Saber Agent Runtime 当前定位不变，把它增强为更真实、更完整、更可解释的 Agent Runtime Workbench / Agent Debug Workbench。

本文档是 Saber Agent Runtime 的后续增强路线图。它不把项目改造成平台化产品，而是继续围绕 Agent 执行过程的调试、解释和演示能力做增强。

Saber 的核心价值仍然是：

> 展示一次复杂 Agent 请求如何被路由、规划、执行、检索、调用工具、注入记忆并生成结果，并用 Trace 解释 Agent 为什么这样做。

当前 README 仍以当前版本真实能力为准。本文中的真实 LLM、Embedding、Vector Search、PostgreSQL、Redis、Docker、MCP Adapter 等均属于后续增强方向，不代表当前版本已经接入。SQLite 本地持久化已作为可选工程增强落地，用于保留 Trace 和上传文档。

## 1. 项目定位保持

### 当前定位

Saber Agent Runtime 当前定位为：

> 面向复杂任务的可观测 Agent 执行系统，用 Trace 解释 Agent 为什么这样路由、规划、调用工具、检索证据和生成回答。

核心链路保持不变：

```text
User -> Router -> Planner -> Executor -> Tools / RAG / Memory -> Generator -> Trace
```

### 不做什么

本路线图明确不把 Saber 扩展成以下方向：

- 不做 LangGraph 替代品
- 不做 Dify 类工作流平台
- 不做组织级 Agent 管理平台
- 不做复杂租户隔离系统
- 不围绕 MCP 建平台
- 不做复杂 Multi-Agent Coordinator 主线

### 升级目标

升级目标不是改变项目架构，而是让一次 Agent 执行过程更加真实、完整、可解释：

- Router 从规则判断增强为可选 LLM 结构化路由。
- Planner 从规则 Plan 增强为 LLM Plan + Validation + Reflection。
- Executor 从顺序执行增强为 Retry、Recovery 和失败定位。
- RAG 从简单检索增强为 Evidence Chain 展示。
- Memory 从轻量 Session Memory 增强为更清晰的上下文来源管理。
- Trace 从 Timeline 增强为 Detail、Replay、Compare。
- UI 从 Runtime Workbench 增强为 Agent Debug Workbench。

## 2. Current Runtime Chain

### 当前链路

```text
User
  |
  v
Router
  |
  v
Planner
  |
  v
Executor
  |
  v
Tools / RAG / Memory
  |
  v
Generator
  |
  v
Trace
```

### 当前已实现能力

- 结构化 Router：`chat / rag / tool / react`
- Router 输出：`confidence / reason / signals`
- 标准 JSON Plan：`id / tool / params / reason / depends_on`
- Tool Registry：`search_repo / read_file / rag_search / generate_report / run_tests`
- 工具调用结构化结果：`params / status / duration / summary / error`
- RAG Evidence：`content / source / score / metadata`
- 轻量 Memory：会话历史、滚动摘要、简单偏好
- Trace Timeline：Router、Planner、Tool Call、RAG、Memory、Generator、Answer
- `/api/chat` 和 `/api/chat/stream` 前后端真实联调
- Mock fallback

### 当前短板

- Router 和 Planner 当前主要是确定性规则，不是模型驱动。
- Generator 当前是演示回答，不是真实 LLM 生成。
- Executor 当前以顺序执行为主，缺少 Retry 和 Recovery 策略。
- RAG 当前是关键词评分，还没有 Embedding、Vector Search 和 Rerank。
- Trace 已能定位阶段，但还可以展示更详细的 Input、Output、State、Evidence 和 Replay 信息。
- 前端 Workbench 已能演示执行链路，但还可以更像 Agent 调试台。

## 3. Enhancement Capability Map

| Module | 当前状态 | 增强方向 | 面试讲法 |
| --- | --- | --- | --- |
| Router | 规则路由 | LLM 结构化路由 + 规则 fallback | 从稳定规则演示升级为真实 Agent 路由能力 |
| Planner | 规则 JSON Plan | LLM Plan + Validation + Reflection | 展示计划生成、校验、修正的闭环 |
| Executor | 顺序执行工具 | Retry + Recovery + 失败 Trace | 让工具失败也变成可解释执行过程 |
| Tool Registry | 工具注册和参数校验 | 工具元数据、风险、超时、调用状态 | 工具不只是函数，而是可治理能力 |
| RAG | 关键词 Top-K | Evidence Chain，后续接 Embedding / Vector Search | 解释检索证据如何进入回答 |
| Memory | 轻量 Session Memory | Conversation / Summary / Preference | 清楚说明本轮注入了哪些上下文 |
| Trace | Timeline | Detail / Replay / Compare | 用 Trace 调试 Agent 行为 |
| Generator | 演示回答 | 真实 LLM 生成 + 引用上下文 | 从流程模拟走向 LLM 驱动 Runtime |
| UI | Workbench | Agent Debug Workbench | 面试时能像调试工具一样演示 Agent 内部机制 |

## 4. Milestone Roadmap

### Milestone 9：LLM Provider Layer

目标：

- 新增统一 LLM Provider 层，为 Router、Planner、Generator 接入真实模型做准备。

核心能力：

- 定义统一接口：`chat / stream / structured_output`
- 支持环境变量配置模型 provider、model name、api key
- 保留规则 fallback，保证无 key 时仍可演示
- Trace 记录 LLM 调用摘要、耗时、失败原因

验收标准：

- 没有 LLM key 时，现有 `/api/chat` 行为保持稳定。
- 配置 LLM key 后，Generator 可以使用真实模型生成回答。
- LLM 调用失败时，Trace 中能看到 fallback 原因。

### Milestone 10：LLM Router & Planner

目标：

- 将 Router 和 Planner 从纯规则增强为 LLM 驱动，同时保留结构化输出和校验。

核心能力：

- Router 使用 LLM 输出 `mode / confidence / reason / signals / selected_tools`
- Planner 使用 LLM 输出 JSON Plan
- Validator 校验工具名、参数和依赖关系
- Plan Reflection 在校验失败时修正 Plan
- 规则 Router / Planner 作为 fallback

验收标准：

- `/api/chat.route` 和 `/api/chat.plan` 字段保持兼容。
- 非法工具名不会进入 Executor。
- 前端 Trace 能展示 LLM Router / Planner 的判断依据和修正过程。

### Milestone 11：Executor Retry & Error Recovery

目标：

- 让工具调用失败不只是报错，而是形成可展示的恢复链路。

核心能力：

- 每个工具支持 `timeout / retry_count / risk_level`
- Executor 根据错误类型执行 Retry 或停止
- 可恢复错误写入 Retry Trace
- 不可恢复错误写入 failed step，并生成解释性 Answer

验收标准：

- 工具失败时 Trace 能展示 failed -> retry -> success 或 failed -> stop。
- `/api/chat.success` 能准确反映最终执行状态。
- 前端 Tool Calls 面板能看到每次尝试的参数、状态、耗时和错误。

### Milestone 12：Trace Detail / Replay / Compare

目标：

- 将 Trace 从阶段 Timeline 升级为 Agent 调试视图。

核心能力：

- Trace Detail 展示每个阶段的 Input、Output、Latency、Reason、Error。
- Trace Replay 保存原始 input、runtime config、route、plan、tool result 摘要。
- Trace Compare 对比两次执行的 route、plan、tool_calls、retrieved_docs、latency、answer。

验收标准：

- `/api/traces/{trace_id}` 能支持 Replay 所需信息。
- 前端 Trace Explorer 能展开查看每个 event 的细节。
- Compare 视图能解释两次运行为什么结果不同。

### Milestone 13：RAG Evidence Explorer

目标：

- 让 RAG 不只显示 retrieved docs，而是展示完整证据链。

核心能力：

- Evidence Explorer 展示 `question -> retrieved chunks -> score -> used context -> answer`
- 后续可选接入 Embedding、Vector Search、Rerank
- Generator 明确引用或总结使用了哪些 evidence
- Trace 中记录 Evidence 是否被 Generator 使用

验收标准：

- 回答旁边能看到 Top-K 证据来源、score、metadata。
- Trace 中能看到检索证据如何进入上下文。
- 即使未接入向量检索，也能稳定展示关键词检索证据链。

### Milestone 14：Agent Debug Workbench UI

目标：

- 将现有 Workbench 强化成更像 Agent 调试台的界面。

核心布局：

- 左侧：Task、Session、Runtime Config、Mock / Real API 开关
- 中间：Router -> Planner -> Executor -> RAG / Memory -> Generator 执行流程
- 右侧：Trace Detail、Evidence、Tool Calls、Memory Context

验收标准：

- 第一屏能看出这是 Agent Debug Workbench。
- 用户能用一个任务观察 route、plan、tool call、rag、memory、answer。
- 工具失败和 RAG 证据不足都能在 UI 中定位。

### Milestone 15：Persistence & Deployment Optional Polish

目标：

- 在保持项目定位的前提下，补充工程完整度。

当前已落地：

- SQLite：可选本地文件持久化 Trace 和 Document
- 简单运行日志和 storage 配置摘要

后续可选能力：

- PostgreSQL：持久化 Trace、Document、Evaluation 样本
- Redis：Session 缓存和轻量执行状态
- Docker：本地一键启动

验收标准：

- README 清楚标注这些能力属于后续增强或可选部署。
- 不把项目叙事改成大型平台化系统。
- 服务重启后可选保留 Trace 和文档数据。

## 5. Not Recommended

为了保持 Saber 的项目定位，不建议加入以下主线：

### LangGraph 替代品

原因：这会把重点从“展示 Agent 执行过程”转成“造框架”，范围过大，不适合作为当前实习项目主线。

### Dify 类工作流平台

原因：Workflow Builder 会改变产品形态，让项目变成低代码编排平台，而不是 Agent Runtime Debug Workbench。

### 组织级权限系统

原因：权限、租户隔离、组织管理会稀释 Agent Runtime 的核心价值，面试展示收益不高。

### 完整 Multi-Agent Coordinator

原因：Multi-Agent 会引入新的主题，容易让 Saber 和业务型 Agent 项目重复或发散。

### 围绕 MCP 建平台

原因：可以支持 MCP Adapter，但不要把 Saber 的核心卖点变成 MCP 生态管理。Saber 的核心仍是 Router、Planner、Executor、RAG、Memory、Trace 的执行解释能力。

## 6. Resume Positioning

### 简历描述

Saber Agent Runtime：面向复杂任务的可观测 Agent 执行工作台，支持结构化 Router、JSON Planner、Tool Calling、RAG 证据展示、轻量 Memory、Trace Timeline 和前后端真实联调。项目后续将增强 LLM Router / Planner、Plan Validation、Executor Retry、Trace Replay / Compare、RAG Evidence Explorer 和 Agent Debug Workbench，用于帮助开发者理解、调试和优化 Agent 执行过程。

### 面试回答：为什么不是 Chatbot？

Chatbot 的重点是生成回答；Saber 的重点是展示回答背后的执行过程。它会解释 Router 为什么这样路由，Planner 生成了哪些步骤，工具调用了什么参数，RAG 检索了哪些证据，Memory 注入了哪些上下文，以及最终回答如何产生。

### 面试回答：为什么不做平台？

Saber 的目标不是做企业平台，而是做一个面试中能讲清 Agent 内部机制的 Runtime Workbench。平台化会引入大量权限、租户、部署、生态管理问题，反而稀释 Router、Planner、Tool Calling、RAG、Memory、Trace 这些核心 Agent 能力。

### 面试回答：真实 LLM 接入有什么价值？

当前规则实现保证演示稳定，但真实 Agent 需要模型参与路由、规划和生成。LLM Provider Layer 可以让 Router、Planner、Generator 接入真实模型，同时保留 fallback，既有真实性，也不牺牲演示稳定性。

### 面试回答：Trace 调试价值在哪里？

复杂 Agent 任务失败时，不能只看最终答案。Trace 可以定位失败发生在路由、计划、工具、RAG、Memory 还是生成阶段，并展示输入、输出、耗时、错误和证据来源，让 Agent 行为可解释、可复盘。

## 7. Boundary Notes

本文档描述的是增强路线，不代表当前代码已经完成全部能力。

当前版本已经实现：

- Router
- Planner
- Executor
- Tool Registry
- RAG Evidence
- Session Memory
- Trace Timeline
- SSE
- React Workbench
- 前后端真实联调

后续增强方向包括：

- LLM Provider Layer
- LLM Router / Planner
- Plan Validation / Reflection
- Executor Retry / Error Recovery
- Trace Detail / Replay / Compare
- RAG Evidence Explorer
- Agent Debug Workbench UI
- 可选 Persistence / Deployment polish

在 README、简历和面试表达中，应始终区分“已实现”和“后续增强”，避免把路线图讲成当前已上线能力。
