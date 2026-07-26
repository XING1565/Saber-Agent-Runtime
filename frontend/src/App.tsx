import { useEffect, useMemo, useState } from 'react';
import { chat as apiChat, healthCheck, listDocuments, uploadDocument } from './api';
import {
  buildGenericTrace,
  buildTrace,
  contextSources,
  demoTasks,
  evaluationMetrics,
  knowledgeDocs,
  memoryItems,
  tools,
} from './mockData';
import type { DemoTaskId, PageId, TraceRun } from './types';

type ChatMessage = {
  id: string;
  role: 'user' | 'agent';
  content: string;
  meta?: string;
};

type ApiStatus = 'checking' | 'connected' | 'unavailable';

const SESSION_ID = 'saber-demo-session';

const navItems: Array<{ id: PageId; label: string }> = [
  { id: 'workbench', label: '调试台' },
  { id: 'tools', label: '工具注册表' },
  { id: 'knowledge', label: 'RAG 证据' },
  { id: 'memory', label: '记忆管理' },
  { id: 'trace', label: '执行追踪' },
  { id: 'evaluation', label: '评测中心' },
];

const pageDescriptions: Record<PageId, string> = {
  workbench: 'Saber Agent 运行时工作台',
  knowledge: '文档检索与证据展示',
  tools: '可调用工具与参数契约',
  memory: '轻量会话记忆与上下文来源',
  trace: '执行链路、时间线和日志',
  evaluation: '任务效果与质量指标',
  settings: 'Mock / UI / 运行配置',
};

const statusText: Record<string, string> = {
  success: '成功',
  running: '运行中',
  pending: '等待中',
  warning: '警告',
  failed: '失败',
  available: '可用',
  mock: '模拟',
  disabled: '停用',
  blocked: '阻塞',
  deferred: '后续',
  planned: '计划中',
};

const modeText: Record<string, string> = {
  react: 'ReAct',
  rag: 'RAG',
  tool: '工具调用',
  chat: '对话',
};

const focusText: Record<string, string> = {
  success: '成功率',
  latency: '耗时',
  rag: 'RAG 命中',
};

const memoryModeOptions = ['会话记忆', '扩展预留'];
function formatMs(ms: number) {
  return `${ms.toLocaleString()} ms`;
}

function formatScore(score: number) {
  return score >= 1 ? `${Math.round(score * 100)}%` : `${score.toFixed(2)}`;
}

function compareTraces(previous: TraceRun, current: TraceRun) {
  const previousTools = previous.toolCalls.map((call) => call.tool).join(' -> ') || 'none';
  const currentTools = current.toolCalls.map((call) => call.tool).join(' -> ') || 'none';
  const previousSources = previous.evidence.map((item) => item.source).join(', ') || 'none';
  const currentSources = current.evidence.map((item) => item.source).join(', ') || 'none';
  const previousAnswer = previous.finalAnswerBullets[0] ?? '';
  const currentAnswer = current.finalAnswerBullets[0] ?? '';
  const reasons = [
    previous.route.mode !== current.route.mode ? '路由模式不同' : '',
    previousTools !== currentTools ? '工具链不同' : '',
    previousSources !== currentSources ? 'RAG 证据来源不同' : '',
    previous.status !== current.status ? '执行状态不同' : '',
    previousAnswer !== currentAnswer ? '回答首句不同' : '',
  ].filter(Boolean);
  return [
    { label: 'Route', value: `${labelMode(previous.route.mode)} -> ${labelMode(current.route.mode)}` },
    { label: 'Plan steps', value: `${previous.plan.steps.length} -> ${current.plan.steps.length}` },
    { label: 'Tools', value: `${previousTools} -> ${currentTools}` },
    { label: 'RAG chunks', value: `${previous.evidence.length} -> ${current.evidence.length}` },
    { label: 'Latency', value: `${formatMs(previous.durationMs)} -> ${formatMs(current.durationMs)}` },
    { label: 'Answer', value: previousAnswer === currentAnswer ? '首句一致' : '首句不同' },
    { label: 'Explain', value: reasons.length ? `两次执行不同主要因为：${reasons.join('、')}。` : '两次执行的核心链路基本一致。' },
  ];
}

function App() {
  const [page, setPage] = useState<PageId>('workbench');
  const [chatInput, setChatInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trace, setTrace] = useState<TraceRun>(() => buildTrace(demoTasks[0]));
  const [previousTrace, setPreviousTrace] = useState<TraceRun | null>(null);
  const [running, setRunning] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mockMode, setMockMode] = useState(true);
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking');
  const [apiError, setApiError] = useState('');
  const [serverDocs, setServerDocs] = useState<typeof knowledgeDocs>([]);
  const [compactTrace, setCompactTrace] = useState(false);
  const [memoryMode, setMemoryMode] = useState('会话记忆');
  const [docFilter, setDocFilter] = useState('');
  const [toolFilter, setToolFilter] = useState('');
  const [selectedDoc, setSelectedDoc] = useState(knowledgeDocs[0]);
  const [kpiFocus, setKpiFocus] = useState<'success' | 'latency' | 'rag'>('success');

  const filteredDocs = useMemo(
    () =>
      knowledgeDocs.filter((doc) =>
        `${doc.title} ${doc.preview} ${doc.type}`.toLowerCase().includes(docFilter.trim().toLowerCase()),
      ),
    [docFilter],
  );

  const filteredTools = useMemo(
    () =>
      tools.filter((tool) =>
        `${tool.name} ${tool.description} ${tool.useCase}`.toLowerCase().includes(toolFilter.trim().toLowerCase()),
      ),
    [toolFilter],
  );

  useEffect(() => {
    setSelectedDoc(filteredDocs[0] ?? knowledgeDocs[0]);
  }, [filteredDocs]);

  useEffect(() => {
    void refreshBackendState();
  }, []);

  async function refreshBackendState() {
    try {
      await healthCheck();
      setApiStatus('connected');
      setApiError('');
      setServerDocs(await listDocuments());
    } catch (error) {
      setApiStatus('unavailable');
      setApiError(error instanceof Error ? error.message : '后端不可用');
    }
  }

  async function runTask(taskId: DemoTaskId, customPrompt?: string): Promise<TraceRun | undefined> {
    if (running) return undefined;
    const task = demoTasks.find((item) => item.id === taskId) ?? demoTasks[0];
    setRunning(true);
    setPage('workbench');
    setPreviousTrace(trace);

    if (!mockMode) {
      const prompt = customPrompt || task.prompt;
      setTrace({
        ...buildGenericTrace(prompt),
        status: 'running',
        finalAnswerTitle: '等待真实后端响应',
        finalAnswerBullets: ['正在调用 /api/chat，并准备映射真实 Trace。'],
      });
      try {
        const backendTrace = await apiChat(prompt, { sessionId: SESSION_ID, useRag: shouldUseRag(prompt, taskId) });
        setTrace(backendTrace);
        setApiStatus('connected');
        setApiError('');
        return backendTrace;
      } catch (error) {
        const message = error instanceof Error ? error.message : '真实后端调用失败';
        setApiStatus('unavailable');
        setApiError(message);
        setTrace((prev) => ({
          ...prev,
          status: 'failed',
          finalAnswerTitle: '真实后端调用失败',
          finalAnswerBullets: [message, '已保留当前页面状态，可切回 Mock 模式继续演示。'],
        }));
      } finally {
        setRunning(false);
      }
      return undefined;
    }

    const startTrace = customPrompt ? buildGenericTrace(customPrompt) : buildTrace(task);
    setTrace({
      ...startTrace,
      status: 'running',
      events: startTrace.events.map((event, index) => ({
        ...event,
        status: index === 0 ? 'running' : 'pending',
      })),
      finalAnswerBullets: customPrompt
        ? ['Mock 适配器模式尚未接入真实后端。', '当前仅展示页面结构与执行链路。']
        : startTrace.finalAnswerBullets,
    });

    const updatedEvents = [...startTrace.events];
    for (let i = 0; i < updatedEvents.length; i += 1) {
      await pause(220 + i * 60);
      setTrace((prev) => ({
        ...prev,
        events: prev.events.map((event, index) => ({
          ...event,
          status: index < i + 1 ? 'success' : index === i + 1 ? 'running' : 'pending',
        })),
        logs: [
          ...prev.logs.slice(0, i),
          prev.logs[i] ?? `[mock] 第 ${i + 1} 步已完成`,
        ],
      }));
    }

    await pause(300);
    setTrace((prev) => ({
      ...prev,
      status: 'success',
      durationMs: customPrompt ? 980 : task.latencyMs,
      tokenCount: customPrompt ? 860 : task.tokenCount,
      routeReason: customPrompt ? 'Mock 适配器自动匹配到演示流' : task.routeReason,
      routeSignals: customPrompt ? ['mock', 'demo'] : task.routeSignals,
      finalAnswerTitle: customPrompt ? '模拟响应' : task.answerTitle,
      finalAnswerBullets: customPrompt
        ? ['当前前端为 Mock 优先模式。', '后续可替换为真实 /api/chat/stream。']
        : task.answerBullets,
    }));
    setRunning(false);
    return customPrompt ? buildGenericTrace(customPrompt) : buildTrace(task);
  }

  async function sendChat() {
    const text = chatInput.trim();
    if (!text || running) return;
    const target = inferTask(text);
    const task = demoTasks.find((item) => item.id === target) ?? demoTasks[0];

    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: 'user', content: text, meta: '用户任务' },
    ]);
    setChatInput('');
    const resultTrace = await runTask(target, text);
    setMessages((prev) => [
      ...prev,
      {
        id: `agent-${Date.now()}`,
        role: 'agent',
        content: mockMode ? task.answerBullets.join('\n') : resultTrace?.finalAnswerBullets.join('\n') ?? '真实后端调用失败，请检查连接状态。',
        meta: mockMode ? `${labelMode(task.mode)} · ${task.toolChain.join(' → ')}` : '真实后端 · /api/chat',
      },
    ]);
  }

  async function runDemoTask(taskId: DemoTaskId) {
    const task = demoTasks.find((item) => item.id === taskId) ?? demoTasks[0];
    setChatInput(task.prompt);
    setMessages((prev) => [
      ...prev,
      { id: `demo-user-${Date.now()}`, role: 'user', content: task.prompt, meta: 'Demo 任务' },
    ]);
    const resultTrace = await runTask(task.id);
    setMessages((prev) => [
      ...prev,
      {
        id: `demo-agent-${Date.now()}`,
        role: 'agent',
        content: mockMode ? task.answerBullets.join('\n') : resultTrace?.finalAnswerBullets.join('\n') ?? '真实后端调用失败，请检查连接状态。',
        meta: mockMode ? `${labelMode(task.mode)} · ${task.toolChain.join(' → ')}` : '真实后端 · /api/chat',
      },
    ]);
  }

  function inferTask(text: string): DemoTaskId {
    const lower = text.toLowerCase();
    if (lower.includes('测试') || lower.includes('失败') || lower.includes('run')) return 'tests';
    if (lower.includes('router') || lower.includes('planner') || lower.includes('executor')) return 'workflow';
    return 'rag-module';
  }

  return (
    <div className={`app-shell ${page === 'trace' ? 'dark-trace' : ''}`}>
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        <div className="brand-row">
          <div className="brand-mark">S</div>
          <div className="brand-copy">
            <div className="brand-title">Saber Agent 运行时</div>
            <div className="brand-sub">可观测 Agent 执行系统</div>
          </div>
        </div>

        <button className="sidebar-toggle" onClick={() => setSidebarOpen((value) => !value)}>
          {sidebarOpen ? '◀' : '▶'}
        </button>

        <div className="sidebar-section">
          <div className="section-label">运行时</div>
          <div className="sidebar-pill success">运行中</div>
        </div>

        <nav className="nav-list">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-main">{item.label}</span>
            </button>
          ))}
        </nav>

      </aside>

      <main className="main-shell">
        {page === 'workbench' && (
          <section className="page-grid workbench-grid chat-only-grid">
            <div className="panel chat-only-panel">
              <div className="panel-head">
                <div>
                  <div className="panel-title">聊天工作台</div>
                </div>
                <div className="workspace-meta">
                  <span className="meta-pill">{mockMode ? 'Mock 执行流' : '真实 /api/chat'}</span>
                  <span className="meta-pill">{labelMode(trace.route.mode)}</span>
                </div>
              </div>

              <div className="chat-shell chat-only-shell">
                <div className="chat-messages">
                  {messages.map((message) => (
                    <div className={`chat-message ${message.role}`} key={message.id}>
                      <div className="chat-avatar">{message.role === 'user' ? '你' : 'S'}</div>
                      <div className="chat-bubble">
                        <div className="chat-meta">{message.meta}</div>
                        <div className="chat-text">
                          {message.content.split('\n').map((line) => (
                            <p key={`${message.id}-${line}`}>{line}</p>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="chat-input-row">
                  <textarea
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        void sendChat();
                      }
                    }}
                    placeholder="输入 Agent 任务，Enter 发送，Shift + Enter 换行..."
                  />
                  <button className="primary-btn chat-send" onClick={() => void sendChat()} disabled={running || !chatInput.trim()}>
                    {running ? '执行中' : '发送'}
                  </button>
                </div>
              </div>
            </div>

            <div className="panel trace-panel aligned-side-panel">
              <div className="panel-head">
                <div>
                  <div className="panel-title">本轮执行观察</div>
                  <div className="panel-desc">路由 / 计划 / 工具调用 / 检索证据 / 记忆</div>
                </div>
                <button className="ghost-btn tiny" onClick={() => setPage('trace')}>
                  详情
                </button>
              </div>

              <div className="side-observe-grid">
                <div className="observe-card">
                  <span>路由</span>
                  <strong>{labelMode(trace.route.mode)} · {formatScore(trace.route.confidence)}</strong>
                  <p>{trace.route.reason}</p>
                </div>
                <div className="observe-card">
                  <span>计划</span>
                  <strong>{trace.plan.steps.length} 步</strong>
                  <p>{trace.plan.goal}</p>
                </div>
                <div className={trace.toolCalls.some((call) => call.status === 'failed') ? 'observe-card failed' : 'observe-card'}>
                  <span>工具调用</span>
                  <strong>{trace.toolCalls.length} 次</strong>
                  <p>{trace.toolCalls.some((call) => call.status === 'failed') ? '存在失败工具，可进入详情定位。' : trace.toolCalls.map((call) => call.tool).join(' -> ')}</p>
                </div>
                <div className={trace.evidence.length ? 'observe-card' : 'observe-card warning'}>
                  <span>检索证据</span>
                  <strong>{trace.evidence.length} 条</strong>
                  <p>{trace.evidence.length ? trace.evidence.map((item) => item.source).slice(0, 2).join(', ') : '本轮没有检索证据。'}</p>
                </div>
              </div>

              <div className="trace-list compact-side-trace">
                {trace.events.map((event) => (
                  <div className={`trace-item ${event.status}`} key={event.id}>
                    <div className="trace-icon">{traceIcon(event.type)}</div>
                    <div className="trace-main">
                      <div className="trace-title-row">
                        <div className="trace-title">{labelTraceTitle(event.title)}</div>
                        {event.durationMs ? <span className="trace-time">{formatMs(event.durationMs)}</span> : null}
                      </div>
                      <div className="trace-detail">{event.detail}</div>
                    </div>
                    <div className={`trace-status ${event.status}`}>{labelStatus(event.status)}</div>
                  </div>
                ))}
              </div>

              <div className="tool-call-mini">
                <div className="section-row">
                  <div className="section-label">工具调用</div>
                  <span className="tiny-muted">{trace.toolCalls.length} 次</span>
                </div>
                {trace.toolCalls.slice(0, 3).map((call) => (
                  <div className={`tool-call-row ${call.status}`} key={`${call.stepId}-${call.tool}`}>
                    <div>
                      <strong>{call.tool}</strong>
                      <span>{call.summary}</span>
                      {call.error ? <span>{call.error.code}: {call.error.message}</span> : null}
                    </div>
                    <em>{formatMs(call.durationMs)}</em>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
        {page === 'trace' && (
          <TraceInspector trace={trace} previousTrace={previousTrace} compact={compactTrace} onCompactChange={setCompactTrace} />
        )}
        {page === 'knowledge' && (
          <KnowledgePage
            docs={filteredDocs}
            serverDocs={serverDocs}
            selectedDoc={selectedDoc}
            onSelectDoc={setSelectedDoc}
            docFilter={docFilter}
            onDocFilter={setDocFilter}
            trace={trace}
            mockMode={mockMode}
            onUploadDocument={async (payload) => {
              const doc = await uploadDocument(payload);
              setServerDocs((prev) => [doc, ...prev.filter((item) => item.id !== doc.id)]);
              setApiStatus('connected');
              setApiError('');
              return doc;
            }}
          />
        )}
        {page === 'tools' && (
          <ToolPage tools={filteredTools} toolFilter={toolFilter} onToolFilter={setToolFilter} />
        )}
        {page === 'memory' && <MemoryPage items={memoryItems} sources={contextSources} memoryMode={memoryMode} onMode={setMemoryMode} />}
        {page === 'evaluation' && <EvaluationPage metrics={evaluationMetrics} trace={trace} focus={kpiFocus} onFocus={setKpiFocus} />}
        {page === 'settings' && (
          <SettingsPage
            mockMode={mockMode}
            onMockMode={setMockMode}
            apiStatus={apiStatus}
            apiError={apiError}
            onRefreshApi={() => void refreshBackendState()}
            compactTrace={compactTrace}
            onCompactTrace={setCompactTrace}
            sidebarOpen={sidebarOpen}
            onSidebarOpen={setSidebarOpen}
            memoryMode={memoryMode}
            onMemoryMode={setMemoryMode}
          />
        )}
      </main>
    </div>
  );
}

function TraceInspector({
  trace,
  previousTrace,
  compact,
  onCompactChange,
}: {
  trace: TraceRun;
  previousTrace: TraceRun | null;
  compact: boolean;
  onCompactChange: (value: boolean) => void;
}) {
  const compare = previousTrace ? compareTraces(previousTrace, trace) : null;
  return (
    <section className="trace-inspector">
      <div className="inspector-hero">
        <div>
          <div className="inspector-kicker">执行检查器</div>
          <h1>Saber Agent Runtime 执行追踪</h1>
          <p>面向开发者的执行流、证据链和日志视图。</p>
        </div>
        <div className="inspector-actions">
          <label className="switch-row">
            <span>紧凑模式</span>
            <input type="checkbox" checked={compact} onChange={(e) => onCompactChange(e.target.checked)} />
          </label>
          <span className="inspector-chip">{trace.traceId}</span>
          <span className="inspector-chip">{labelStatus(trace.status)}</span>
        </div>
      </div>

      <div className="inspector-grid">
        <div className="panel dark-panel graph-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">执行图</div>
              <div className="panel-desc">{'Router -> Planner -> Tools / RAG / Memory -> Generator -> Answer'}</div>
            </div>
          </div>
          <div className="graph-flow">
            <GraphNode label="Router" detail={`模式：${labelMode(trace.route.mode)}`} />
            <GraphNode label="Planner" detail={`${trace.plan.steps.length} 个步骤`} />
            <div className="branch-row">
              <GraphNode label="search_repo" detail="工具" />
              <GraphNode label="read_file" detail="工具" />
              <GraphNode label="rag_search" detail="证据" />
            </div>
            <GraphNode label="Memory" detail="轻量上下文" />
            <GraphNode label="Generator" detail="最终回答" />
            <GraphNode label="Answer" detail="写入 Trace" />
          </div>
        </div>

        <div className="panel dark-panel timeline-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">工具时间线</div>
              <div className="panel-desc">按时间顺序查看执行步骤</div>
            </div>
          </div>
          <div className={`timeline-list ${compact ? 'compact' : ''}`}>
            {trace.events.map((event, index) => (
              <div className={`timeline-item ${event.status}`} key={event.id}>
                <div className="timeline-index">{index + 1}</div>
                <div className="timeline-main">
                  <div className="timeline-head">
                    <strong>{event.title}</strong>
                    <span>{event.durationMs ? formatMs(event.durationMs) : '运行中'}</span>
                  </div>
                  <div className="timeline-detail">{event.detail}</div>
                  <details className="event-detail">
                    <summary>Input / Output / Error</summary>
                    <div className="detail-grid">
                      <div>
                        <strong>Input</strong>
                        <pre>{JSON.stringify(event.rawInput ?? event.meta ?? {}, null, 2)}</pre>
                      </div>
                      <div>
                        <strong>Output</strong>
                        <pre>{event.outputSummary ?? event.detail}</pre>
                      </div>
                      <div>
                        <strong>Error</strong>
                        <pre>{JSON.stringify(event.rawError ?? null, null, 2)}</pre>
                      </div>
                    </div>
                  </details>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel dark-panel log-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">执行日志</div>
              <div className="panel-desc">摘要日志与状态信息</div>
            </div>
          </div>
          <div className="log-list">
            {trace.logs.map((line) => (
              <div className="log-line" key={line}>
                {line}
              </div>
            ))}
          </div>
        </div>

        <div className="panel dark-panel tool-call-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">工具调用</div>
              <div className="panel-desc">参数 / 状态 / 耗时 / 摘要</div>
            </div>
            <span className="inspector-chip">{trace.toolCalls.length} 次</span>
          </div>
          <div className="tool-call-list">
            {trace.toolCalls.map((call) => (
              <article className={`tool-call-card ${call.status}`} key={`${call.stepId}-${call.tool}`}>
                <div className="tool-call-head">
                  <div>
                    <strong>{call.tool}</strong>
                    <span>{call.stepId}</span>
                  </div>
                  <div className="tool-call-badges">
                    <span>{call.status}</span>
                    <span>{formatMs(call.durationMs)}</span>
                    {call.riskLevel ? <span>{call.riskLevel}</span> : null}
                  </div>
                </div>
                <div className="tool-call-summary">
                  {call.summary}
                  {call.attempts?.length ? ` · ${call.attempts.length} attempts · ${call.recovery?.summary ?? 'success'}` : ''}
                </div>
                <pre>{JSON.stringify(call.params, null, 2)}</pre>
                {call.attempts?.length && call.attempts.length > 1 ? (
                  <pre>{JSON.stringify(call.attempts, null, 2)}</pre>
                ) : null}
                {call.error ? (
                  <div className="tool-call-error">
                    {call.error.code}: {call.error.message}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </div>

        <div className="panel dark-panel why-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">Why This Run</div>
              <div className="panel-desc">用 Trace 回答 Agent 为什么这么做</div>
            </div>
          </div>
          <div className="why-list">
            <div>
              <span>Router reason</span>
              <strong>{trace.route.reason}</strong>
            </div>
            <div>
              <span>Signals</span>
              <strong>{trace.route.signals.join(', ')}</strong>
            </div>
            <div>
              <span>Planner goal</span>
              <strong>{trace.plan.goal}</strong>
            </div>
          </div>
        </div>

        <div className="panel dark-panel compare-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">Current vs Previous</div>
              <div className="panel-desc">对比最近两次 Trace 的 route / plan / tools / RAG / latency / answer</div>
            </div>
            <span className="inspector-chip">{previousTrace ? previousTrace.traceId : 'no previous'}</span>
          </div>
          {compare ? (
            <div className="why-list">
              {compare.map((item) => (
                <div key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          ) : (
            <div className="trace-detail">运行第二次任务后，这里会展示与上一条 Trace 的差异。</div>
          )}
        </div>

        <div className="panel dark-panel context-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">Context Sources</div>
              <div className="panel-desc">Memory injection for this run</div>
            </div>
            <span className="inspector-chip">lightweight</span>
          </div>
          <div className="context-source-list">
            <div>
              <strong>Session history</strong>
              <span>最近多轮 user / assistant 消息，用于读取前文。</span>
            </div>
            <div>
              <strong>Rolling summary</strong>
              <span>保留必要历史摘要，避免把完整长对话当作当前能力主卖点。</span>
            </div>
            <div>
              <strong>Simple preference</strong>
              <span>只记录显式表达的偏好，例如“先给结论”。复杂长期记忆后续扩展。</span>
            </div>
          </div>
        </div>

        <div className="panel dark-panel evidence-chain-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">Evidence Explorer</div>
              <div className="panel-desc">{'question -> retrieved chunks -> score -> used context -> answer'}</div>
            </div>
            <span className="inspector-chip">{trace.evidenceChain?.retrievalMethod ?? 'keyword'}</span>
          </div>
          {trace.evidenceChain ? (
            <div className="evidence-chain">
              <div>
                <span>Question</span>
                <strong>{trace.evidenceChain.question}</strong>
              </div>
              <div>
                <span>Answer Reference</span>
                <strong>{trace.evidenceChain.answerReference.summary ?? `${trace.evidenceChain.answerReference.usedChunkCount ?? 0} chunks used`}</strong>
              </div>
              <div className="chain-chunks">
                {trace.evidenceChain.retrievedChunks.length ? (
                  trace.evidenceChain.retrievedChunks.map((chunk) => (
                    <article className="retrieved-card" key={`${chunk.rank}-${chunk.source}`}>
                      <div className="retrieved-head">
                        <strong>#{chunk.rank} {chunk.source}</strong>
                        <span>{formatScore(chunk.score)}</span>
                      </div>
                      <div className="retrieved-content">{chunk.content}</div>
                      <div className="retrieved-meta">
                        {chunk.usedByGenerator ? 'used by Generator' : 'not used'} · {formatMetadata(chunk.metadata)}
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="trace-detail">本轮没有 retrieved chunks，Generator 未注入 RAG used context。</div>
                )}
              </div>
              <details className="event-detail">
                <summary>Used Context</summary>
                <pre>{trace.evidenceChain.usedContext || '无 used context'}</pre>
              </details>
            </div>
          ) : (
            <div className="trace-detail">当前 Trace 未包含 evidence_chain。</div>
          )}
        </div>

        <div className="panel dark-panel retrieved-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">Retrieved Chunks</div>
              <div className="panel-desc">RAG evidence injected into Generator context</div>
            </div>
            <span className="inspector-chip">{trace.evidence.length} chunks</span>
          </div>
          <div className="retrieved-list">
            {trace.evidence.map((item) => (
              <article className="retrieved-card" key={`${item.source}-${item.chunk ?? item.content}`}>
                <div className="retrieved-head">
                  <strong>{item.source}</strong>
                  <span>{formatScore(item.score)}</span>
                </div>
                <div className="retrieved-content">{item.content ?? item.excerpt}</div>
                <div className="retrieved-meta">{item.chunk ?? 'retrieved chunk'} · {formatMetadata(item.metadata)}</div>
              </article>
            ))}
          </div>
        </div>

        <div className="panel dark-panel answer-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">Answer</div>
              <div className="panel-desc">最终回答写入 Trace，可回放和排查</div>
            </div>
          </div>
          <div className="answer-title">{trace.finalAnswerTitle}</div>
          <ul className="answer-list">
            {trace.finalAnswerBullets.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>

        <div className="panel dark-panel metric-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">执行指标</div>
              <div className="panel-desc">耗时 / 工具调用 / Token / 成功率</div>
            </div>
          </div>
          <div className="metric-grid">
            <MetricTile label="总耗时" value={formatMs(trace.durationMs)} />
            <MetricTile label="工具调用" value={String(trace.toolCalls.length)} />
            <MetricTile label="Tokens" value={trace.tokenCount.toLocaleString()} />
            <MetricTile label="证据片段" value={String(trace.evidence.length)} />
          </div>
        </div>
      </div>
    </section>
  );
}

function KnowledgePage({
  docs,
  serverDocs,
  selectedDoc,
  onSelectDoc,
  docFilter,
  onDocFilter,
  trace,
  mockMode,
  onUploadDocument,
}: {
  docs: typeof knowledgeDocs;
  serverDocs: typeof knowledgeDocs;
  selectedDoc: typeof knowledgeDocs[number];
  onSelectDoc: (doc: typeof knowledgeDocs[number]) => void;
  docFilter: string;
  onDocFilter: (value: string) => void;
  trace: TraceRun;
  mockMode: boolean;
  onUploadDocument: (payload: { title: string; content: string; metadata: Record<string, string> }) => Promise<typeof knowledgeDocs[number]>;
}) {
  const [uploadTitle, setUploadTitle] = useState('Trace 面试说明');
  const [uploadContent, setUploadContent] = useState('Router 负责选择模式。\n\nPlanner 生成步骤。Trace 展示 retrieved chunks 和证据来源。');
  const [uploadMetadata, setUploadMetadata] = useState('source=upload://trace-interview.md; kind=interview-note');
  const [uploadedDocs, setUploadedDocs] = useState<typeof knowledgeDocs>([]);
  const visibleDocs = [...uploadedDocs, ...serverDocs, ...docs];
  const [uploadState, setUploadState] = useState('');

  async function addDocument() {
    const title = uploadTitle.trim();
    const content = uploadContent.trim();
    if (!title || !content) return;
    try {
      const doc = mockMode
        ? {
        id: `uploaded-${Date.now()}`,
        title,
        type: 'uploaded text',
        chunks: Math.max(1, content.split('\n\n').filter(Boolean).length),
        score: 0.99,
        updatedAt: '刚刚',
        preview: content.slice(0, 96),
          }
        : await onUploadDocument({ title, content, metadata: parseMetadata(uploadMetadata) });
      if (mockMode) {
        setUploadedDocs((prev) => [doc, ...prev]);
      }
      setUploadState(mockMode ? '已加入本地 Mock 文档库' : '已上传到后端 /api/documents');
    } catch (error) {
      setUploadState(error instanceof Error ? error.message : '上传失败，已保留页面状态');
    }
  }

  return (
    <section className="page-grid knowledge-grid">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="panel-title">文档库</div>
            <div className="panel-desc">{mockMode ? 'Mock 文档库与检索测试' : '真实 /api/documents 文档库'}</div>
          </div>
        </div>
        <div className="upload-box">
          <div className="section-label">Upload Text</div>
          <input value={uploadTitle} onChange={(e) => setUploadTitle(e.target.value)} placeholder="文档标题" />
          <textarea value={uploadContent} onChange={(e) => setUploadContent(e.target.value)} placeholder="粘贴文档正文，空行会被切成 chunk" />
          <input value={uploadMetadata} onChange={(e) => setUploadMetadata(e.target.value)} placeholder="metadata，例如 source=upload://demo.md" />
          <button className="primary-btn" onClick={() => void addDocument()}>{mockMode ? '加入轻量文档库' : '上传到后端文档库'}</button>
          <div className="tiny-muted">{uploadState || '后端接口形态：POST /api/documents · JSON 上传 · 进程内检索'}</div>
        </div>
        <input className="filter-input" value={docFilter} onChange={(e) => onDocFilter(e.target.value)} placeholder="搜索文档..." />
        <div className="doc-listing">
          {visibleDocs.map((doc) => (
            <button key={doc.id} className={`doc-row ${doc.id === selectedDoc.id ? 'active' : ''}`} onClick={() => onSelectDoc(doc)}>
              <div>
                <div className="doc-title">{doc.title}</div>
                <div className="doc-preview">{doc.preview}</div>
              </div>
              <div className="doc-meta">
                <span>{doc.chunks} 个片段</span>
                <strong>{formatScore(doc.score)}</strong>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="panel-title">检索测试</div>
            <div className="panel-desc">RAG 查询与证据卡片</div>
          </div>
          <span className="meta-pill">追踪 {trace.traceId}</span>
        </div>
        <div className="search-box">
          <div className="section-label">查询</div>
          <div className="search-query">{trace.prompt}</div>
        </div>
        <div className="evidence-grid single">
          {trace.evidence.map((item) => (
            <article className="evidence-card" key={item.source}>
              <div className="evidence-top">
                <strong>{item.source}</strong>
                <span>{formatScore(item.score)}</span>
              </div>
              <div className="evidence-excerpt">{item.content ?? item.excerpt}</div>
              <div className="evidence-meta">{item.chunk ?? 'retrieved chunk'} · {formatMetadata(item.metadata)}</div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function ToolPage({
  tools,
  toolFilter,
  onToolFilter,
}: {
  tools: typeof import('./mockData').tools;
  toolFilter: string;
  onToolFilter: (value: string) => void;
}) {
  return (
    <section className="page-stack">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="panel-title">工具注册表</div>
            <div className="panel-desc">工具描述、参数 schema 和最近调用记录</div>
          </div>
        </div>
        <input className="filter-input" value={toolFilter} onChange={(e) => onToolFilter(e.target.value)} placeholder="搜索工具..." />
        <div className="tool-grid">
          {tools.map((tool) => (
            <article className="tool-card" key={tool.name}>
              <div className="tool-head">
                <div>
                  <div className="tool-name">{tool.name}</div>
                  <div className="tool-desc">{tool.description}</div>
                </div>
                <span className={`tool-state ${tool.status}`}>{labelStatus(tool.status)}</span>
              </div>
              <div className="tool-params">
                {tool.params.map((param) => (
                  <div className="tool-param" key={`${tool.name}-${param.name}`}>
                    <div className="param-name">{param.name}</div>
                  <div className="param-detail">
                    {param.type}
                    {param.required ? ' · 必填' : ''}
                    </div>
                    <div className="param-detail muted">{param.description}</div>
                  </div>
                ))}
              </div>
              <div className="tool-footer">
                <span>{tool.useCase}</span>
                <strong>{tool.lastCall}</strong>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function MemoryPage({
  items,
  sources,
  memoryMode,
  onMode,
}: {
  items: typeof memoryItems;
  sources: typeof contextSources;
  memoryMode: string;
  onMode: (value: string) => void;
}) {
  return (
    <section className="page-stack">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="panel-title">记忆管理</div>
            <div className="panel-desc">当前实现轻量会话历史、滚动摘要和简单偏好；三层记忆作为后续扩展</div>
          </div>
          <div className="segmented">
            {memoryModeOptions.map((mode) => (
              <button key={mode} className={memoryMode === mode ? 'active' : ''} onClick={() => onMode(mode)}>
                {mode}
              </button>
            ))}
          </div>
        </div>

        <div className="memory-layout">
          <div className="memory-list">
            {items.map((item) => (
              <article className="memory-card" key={item.id}>
                <div className="memory-head">
                  <strong>{item.title}</strong>
                  <span>{item.updatedAt}</span>
                </div>
                <div className="memory-body">{item.content}</div>
                <div className="memory-kind">{item.kind}</div>
              </article>
            ))}
          </div>

          <div className="memory-preview">
            <div className="preview-box">
              <div className="panel-title">后续记忆扩展</div>
              <div className="layer-list">
                <div className="layer-item active">
                  <strong>当前：轻量会话记忆</strong>
                  <span>最近多轮消息、必要摘要、简单偏好</span>
                </div>
                <div className="layer-item">
                  <strong>后续：长期记忆</strong>
                  <span>稳定事实、跨会话偏好和可检索知识沉淀</span>
                </div>
                <div className="layer-item">
                  <strong>后续：三层记忆</strong>
                  <span>短期上下文、摘要记忆、长期偏好分层治理</span>
                </div>
              </div>
            </div>
            <div className="preview-box">
              <div className="panel-title">上下文来源</div>
              <div className="source-list">
                {sources.map((source) => (
                  <div className={`source-row ${source.active ? 'active' : ''}`} key={source.name}>
                    <div>
                      <strong>{source.name}</strong>
                      <div className="source-detail">{source.detail}</div>
                    </div>
                    <span>{source.active ? '启用' : '关闭'}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function EvaluationPage({
  metrics,
  trace,
  focus,
  onFocus,
}: {
  metrics: typeof evaluationMetrics;
  trace: TraceRun;
  focus: 'success' | 'latency' | 'rag';
  onFocus: (value: 'success' | 'latency' | 'rag') => void;
}) {
  const failedTasks = [
    { name: '外部仓库分析', reason: '未纳入 V1 范围', status: 'blocked' },
    { name: '复杂 ZIP 解析', reason: '后续扩展项', status: 'deferred' },
    { name: 'Trace 持久化存储', reason: '当前使用进程内存储', status: 'planned' },
  ];

  return (
    <section className="page-stack">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="panel-title">评测中心</div>
            <div className="panel-desc">质量指标、任务完成率和失败任务清单</div>
          </div>
          <div className="segmented compact">
            {['success', 'latency', 'rag'].map((item) => (
              <button key={item} className={focus === item ? 'active' : ''} onClick={() => onFocus(item as typeof focus)}>
                {focusText[item]}
              </button>
            ))}
          </div>
        </div>

        <div className="metric-strip">
          {metrics.map((metric) => (
            <article className="metric-card" key={metric.name}>
              <div className="metric-name">{metric.name}</div>
              <div className="metric-value">
                {metric.value}
                <span>{metric.unit}</span>
              </div>
              <div className="metric-note">{metric.note}</div>
            </article>
          ))}
        </div>

        <div className="evaluation-grid">
          <div className="panel soft-panel">
            <div className="panel-title">当前关注点</div>
            <div className="focus-box">
              {focus === 'success' && '当前重点关注任务成功率和 Demo 稳定性。'}
              {focus === 'latency' && '当前重点关注执行耗时，尤其是多步任务的响应速度。'}
              {focus === 'rag' && '当前重点关注检索命中率和上下文注入质量。'}
            </div>
            <div className="summary-row">
              <span>Trace 状态</span>
              <strong>{labelStatus(trace.status)}</strong>
            </div>
            <div className="summary-row">
              <span>Token 数量</span>
              <strong>{trace.tokenCount.toLocaleString()}</strong>
            </div>
          </div>

          <div className="panel soft-panel">
            <div className="panel-title">失败任务</div>
            <div className="failure-list">
              {failedTasks.map((item) => (
                <div className="failure-item" key={item.name}>
                  <div className="failure-title">{item.name}</div>
                  <div className="failure-reason">{item.reason}</div>
                  <span className={`failure-status ${item.status}`}>{labelStatus(item.status)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function SettingsPage({
  mockMode,
  onMockMode,
  apiStatus,
  apiError,
  onRefreshApi,
  compactTrace,
  onCompactTrace,
  sidebarOpen,
  onSidebarOpen,
  memoryMode,
  onMemoryMode,
}: {
  mockMode: boolean;
  onMockMode: (value: boolean) => void;
  apiStatus: ApiStatus;
  apiError: string;
  onRefreshApi: () => void;
  compactTrace: boolean;
  onCompactTrace: (value: boolean) => void;
  sidebarOpen: boolean;
  onSidebarOpen: (value: boolean) => void;
  memoryMode: string;
  onMemoryMode: (value: string) => void;
}) {
  return (
    <section className="page-stack">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="panel-title">系统设置</div>
            <div className="panel-desc">前端运行模式与展示偏好</div>
          </div>
        </div>

        <div className="settings-grid">
          <ToggleCard
            title="Mock 适配器"
            description="开启时使用本地 Mock，关闭时调用真实 /api/chat。"
            enabled={mockMode}
            onChange={onMockMode}
          />
          <ToggleCard
            title="紧凑 Trace"
            description="执行追踪检查器采用紧凑模式展示更多步骤。"
            enabled={compactTrace}
            onChange={onCompactTrace}
          />
          <ToggleCard
            title="展开侧边栏"
            description="控制左侧导航是否展开。"
            enabled={sidebarOpen}
            onChange={onSidebarOpen}
          />
        </div>

        <div className="settings-box">
          <div className="panel-title">记忆模式</div>
          <div className="segmented">
            {memoryModeOptions.map((mode) => (
              <button key={mode} className={memoryMode === mode ? 'active' : ''} onClick={() => onMemoryMode(mode)}>
                {mode}
              </button>
            ))}
          </div>
        </div>

        <div className="settings-box">
          <div className="panel-title">API 联调入口</div>
          <div className="bridge-note">
            当前 API：<code>{import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}</code>
            <br />
            状态：{labelApiStatus(apiStatus, mockMode)}{apiError ? ` · ${apiError}` : ''}
          </div>
          <button className="ghost-btn settings-refresh" onClick={onRefreshApi}>
            刷新连接
          </button>
        </div>
      </div>
    </section>
  );
}

function ToggleCard({
  title,
  description,
  enabled,
  onChange,
}: {
  title: string;
  description: string;
  enabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="toggle-card">
      <div className="toggle-copy">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <input type="checkbox" checked={enabled} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function GraphNode({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="graph-node">
      <strong>{label}</strong>
      <span>{detail}</span>
    </div>
  );
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function traceIcon(type: string) {
  switch (type) {
    case 'route':
      return 'R';
    case 'plan':
      return 'P';
    case 'tool_call':
      return 'T';
    case 'rag':
      return 'K';
    case 'memory':
      return 'M';
    case 'generator':
      return 'G';
    case 'answer':
      return 'A';
    default:
      return '·';
  }
}

function labelStatus(status: string) {
  return statusText[status] ?? status;
}

function labelMode(mode: string) {
  return modeText[mode] ?? mode;
}

function labelTraceTitle(title: string) {
  if (title === 'Router') return '路由判断';
  if (title === 'Planner') return '计划生成';
  if (title === 'RAG Retrieval') return '证据检索';
  if (title === 'Memory') return '记忆注入';
  if (title === 'Generator') return '回答生成';
  if (title === 'Answer') return '最终回答';
  if (title.startsWith('Tool Call:')) return `工具调用：${title.replace('Tool Call:', '').trim()}`;
  return title;
}

function labelApiStatus(status: ApiStatus, mockMode: boolean) {
  if (mockMode) return 'Mock 模式';
  if (status === 'connected') return '后端已连接';
  if (status === 'checking') return '后端检查中';
  return '后端不可用';
}

function shouldUseRag(prompt: string, taskId: DemoTaskId) {
  const lower = prompt.toLowerCase();
  return taskId === 'workflow' || lower.includes('rag') || prompt.includes('文档') || prompt.includes('资料') || prompt.includes('基于');
}

function formatMetadata(metadata: string | Record<string, string | number | boolean>) {
  if (typeof metadata === 'string') return metadata;
  return Object.entries(metadata)
    .map(([key, value]) => `${key}: ${value}`)
    .join(' · ');
}

function parseMetadata(input: string) {
  return input
    .split(';')
    .map((item) => item.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, item) => {
      const [key, ...rest] = item.split('=');
      if (key && rest.length) {
        acc[key.trim()] = rest.join('=').trim();
      }
      return acc;
    }, {});
}

function pause(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default App;




