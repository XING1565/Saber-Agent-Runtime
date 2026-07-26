import type { KnowledgeDocument, RagEvidence, RouteMode, TraceEventType, TraceRun } from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

type BackendPlanStep = {
  id: string;
  tool: string;
  params: Record<string, string | number | boolean | string[]>;
  reason: string;
  depends_on: string[];
};

type BackendTraceEvent = {
  id: string;
  type: TraceEventType;
  name: string;
  status: 'success' | 'failed' | 'warning';
  input: Record<string, unknown>;
  output_summary: string;
  duration_ms: number;
  error: { code?: string; message?: string } | string | null;
};

type BackendToolCall = {
  tool: string;
  step_id: string;
  params: Record<string, string | number | boolean | string[]>;
  status: 'success' | 'failed';
  duration_ms: number;
  summary: string;
  output: Record<string, unknown>;
  error: { code: string; message: string } | null;
  attempts?: Array<{
    attempt: number;
    status: 'success' | 'failed';
    params: Record<string, string | number | boolean | string[]>;
    duration_ms: number;
    summary: string;
    error: { code: string; message: string } | null;
  }>;
  retry_count?: number;
  risk_level?: string;
  recovery?: {
    status: string;
    strategy: string;
    summary: string;
  };
};

type BackendTrace = {
  trace_id: string;
  task: string;
  status: 'success' | 'failed';
  route: {
    mode: RouteMode;
    confidence: number;
    reason: string;
    signals: string[];
    selected_tools: string[];
  };
  plan: {
    goal: string;
    steps: BackendPlanStep[];
    validation_errors: string[];
  };
  events: BackendTraceEvent[];
  tool_calls: BackendToolCall[];
  retrieved_docs: Array<{
    id?: string;
    source: string;
    score: number;
    content: string;
    metadata: RagEvidence['metadata'];
  }>;
  evidence_chain?: {
    question: string;
    retrieval_method: string;
    retrieved_chunks: Array<{
      rank: number;
      used_by_generator: boolean;
      score: number;
      source: string;
      metadata: RagEvidence['metadata'];
      content: string;
    }>;
    used_context: string;
    answer_reference: {
      used_chunk_count?: number;
      sources?: string[];
      summary?: string;
    };
  };
  final_answer: string;
  total_duration_ms: number;
  replay?: Record<string, unknown>;
  runtime_config?: Record<string, unknown>;
};

type ChatResponse = {
  answer: string;
  trace: BackendTrace;
};

type DocumentResponse = {
  id: string;
  title: string;
  source: string;
  metadata: Record<string, string | number | boolean>;
  chunk_count: number;
  created_at: string;
};

export async function healthCheck() {
  return request<{ status: string }>('/health');
}

export async function chat(message: string, options: { sessionId: string; useRag?: boolean }) {
  const response = await request<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message,
      session_id: options.sessionId,
      use_rag: options.useRag ?? false,
    }),
  });
  return mapTrace(response);
}

export async function streamChat(
  message: string,
  options: { sessionId: string; useRag?: boolean; onEvent: (event: string, payload: unknown) => void },
) {
  const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: options.sessionId,
      use_rag: options.useRag ?? false,
    }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const event = part.match(/^event: (.+)$/m)?.[1] ?? 'message';
      const data = part.match(/^data: (.+)$/m)?.[1];
      if (data) options.onEvent(event, JSON.parse(data));
    }
  }
}

export async function listDocuments() {
  const docs = await request<DocumentResponse[]>('/api/documents');
  return docs.map(mapDocument);
}

export async function uploadDocument(payload: { title: string; content: string; metadata: Record<string, string> }) {
  const doc = await request<DocumentResponse>('/api/documents', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return mapDocument(doc);
}

export async function getMemory(sessionId: string) {
  return request<Record<string, unknown>>(`/api/memory/${encodeURIComponent(sessionId)}`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function mapTrace(response: ChatResponse): TraceRun {
  const trace = response.trace;
  const answerLines = response.answer.split('\n').filter(Boolean);
  return {
    traceId: trace.trace_id,
    taskId: 'custom',
    taskTitle: trace.task,
    prompt: trace.task,
    mode: trace.route.mode,
    confidence: trace.route.confidence,
    route: {
      mode: trace.route.mode,
      confidence: trace.route.confidence,
      reason: trace.route.reason,
      signals: trace.route.signals,
      selectedTools: trace.route.selected_tools,
    },
    plan: {
      goal: trace.plan.goal,
      validationErrors: trace.plan.validation_errors,
      steps: trace.plan.steps.map((step) => ({
        id: step.id,
        tool: step.tool,
        params: step.params,
        reason: step.reason,
        dependsOn: step.depends_on,
      })),
    },
    status: trace.status,
    startedAt: 'backend',
    durationMs: trace.total_duration_ms,
    tokenCount: estimateTokens(response.answer),
    routeReason: trace.route.reason,
    routeSignals: trace.route.signals,
    steps: trace.events.map((event) => `${event.name}: ${event.output_summary}`),
    toolChain: trace.tool_calls.map((call) => call.tool),
    toolCalls: trace.tool_calls.map((call) => ({
      tool: call.tool,
      stepId: call.step_id,
      params: call.params,
      status: call.status,
      durationMs: call.duration_ms,
      summary: call.summary,
      output: call.output,
      error: call.error,
      attempts: call.attempts?.map((attempt) => ({
        attempt: attempt.attempt,
        status: attempt.status,
        params: attempt.params,
        durationMs: attempt.duration_ms,
        summary: attempt.summary,
        error: attempt.error,
      })),
      retryCount: call.retry_count,
      riskLevel: call.risk_level,
      recovery: call.recovery,
    })),
    events: trace.events.map((event) => ({
      id: event.id,
      type: event.type,
      title: event.name,
      detail: event.error ? `${event.output_summary} · ${formatError(event.error)}` : event.output_summary,
      status: event.status,
      durationMs: event.duration_ms,
      meta: { source: 'backend' },
      rawInput: event.input,
      outputSummary: event.output_summary,
      rawError: event.error,
    })),
    evidence: trace.retrieved_docs.map((doc) => ({
      source: doc.source,
      score: doc.score,
      content: doc.content,
      chunk: doc.id ?? 'retrieved chunk',
      metadata: doc.metadata,
    })),
    evidenceChain: trace.evidence_chain
      ? {
        question: trace.evidence_chain.question,
        retrievalMethod: trace.evidence_chain.retrieval_method,
        retrievedChunks: trace.evidence_chain.retrieved_chunks.map((chunk) => ({
          rank: chunk.rank,
          usedByGenerator: chunk.used_by_generator,
          score: chunk.score,
          source: chunk.source,
          metadata: chunk.metadata,
          content: chunk.content,
        })),
        usedContext: trace.evidence_chain.used_context,
        answerReference: trace.evidence_chain.answer_reference,
      }
      : undefined,
    finalAnswerTitle: '真实后端回答',
    finalAnswerBullets: answerLines,
    logs: trace.events.map((event) => `[backend] ${event.name} -> ${event.status}`),
    rawTrace: trace as unknown as Record<string, unknown>,
    replay: trace.replay,
    runtimeConfig: trace.runtime_config,
  };
}

function mapDocument(doc: DocumentResponse): KnowledgeDocument {
  return {
    id: doc.id,
    title: doc.title,
    type: 'backend text',
    chunks: doc.chunk_count,
    score: 1,
    updatedAt: doc.created_at,
    preview: `${doc.source} · ${Object.entries(doc.metadata).map(([key, value]) => `${key}:${value}`).join(' ')}`,
  };
}

function estimateTokens(text: string) {
  return Math.max(1, Math.round(text.length / 2));
}

function formatError(error: BackendTraceEvent['error']) {
  if (!error) return '';
  if (typeof error === 'string') return error;
  return `${error.code ?? 'error'}: ${error.message ?? ''}`;
}
