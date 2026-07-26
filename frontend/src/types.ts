export type PageId =
  | 'workbench'
  | 'trace'
  | 'knowledge'
  | 'tools'
  | 'memory'
  | 'evaluation'
  | 'settings';

export type DemoTaskId = 'rag-module' | 'workflow' | 'tests';

export type RouteMode = 'chat' | 'rag' | 'tool' | 'react';

export interface RouteDecision {
  mode: RouteMode;
  confidence: number;
  reason: string;
  signals: string[];
  selectedTools: string[];
}

export interface PlanStep {
  id: string;
  tool: string;
  params: Record<string, string | number | boolean | string[]>;
  reason: string;
  dependsOn: string[];
}

export interface ExecutionPlan {
  goal: string;
  steps: PlanStep[];
  validationErrors: string[];
}

export interface ToolCallResult {
  tool: string;
  stepId: string;
  params: Record<string, string | number | boolean | string[]>;
  status: 'success' | 'failed';
  durationMs: number;
  summary: string;
  output: Record<string, unknown>;
  error: {
    code: string;
    message: string;
  } | null;
  attempts?: ToolCallAttempt[];
  retryCount?: number;
  riskLevel?: string;
  recovery?: ToolRecovery;
}

export interface ToolCallAttempt {
  attempt: number;
  status: 'success' | 'failed';
  params: Record<string, string | number | boolean | string[]>;
  durationMs: number;
  summary: string;
  error: {
    code: string;
    message: string;
  } | null;
}

export interface ToolRecovery {
  status: string;
  strategy: string;
  summary: string;
}

export type TraceEventType =
  | 'route'
  | 'plan'
  | 'tool_call'
  | 'rag'
  | 'memory'
  | 'generator'
  | 'answer'
  | 'log';

export interface DemoTask {
  id: DemoTaskId;
  title: string;
  subtitle: string;
  prompt: string;
  mode: 'react' | 'rag' | 'tool';
  confidence: number;
  route: RouteDecision;
  plan: ExecutionPlan;
  routeReason: string;
  routeSignals: string[];
  steps: string[];
  toolChain: string[];
  toolCalls: ToolCallResult[];
  answerTitle: string;
  answerBullets: string[];
  tokenCount: number;
  latencyMs: number;
  evidenceCount: number;
}

export interface TraceEvent {
  id: string;
  type: TraceEventType;
  title: string;
  detail: string;
  status: 'success' | 'running' | 'pending' | 'warning' | 'failed';
  durationMs?: number;
  meta?: Record<string, string | number | boolean>;
  rawInput?: Record<string, unknown>;
  outputSummary?: string;
  rawError?: unknown;
}

export interface TraceRun {
  traceId: string;
  taskId: DemoTaskId | 'custom';
  taskTitle: string;
  prompt: string;
  mode: string;
  confidence: number;
  route: RouteDecision;
  plan: ExecutionPlan;
  status: 'running' | 'success' | 'failed';
  startedAt: string;
  durationMs: number;
  tokenCount: number;
  routeReason: string;
  routeSignals: string[];
  steps: string[];
  toolChain: string[];
  toolCalls: ToolCallResult[];
  events: TraceEvent[];
  evidence: RagEvidence[];
  evidenceChain?: EvidenceChain;
  finalAnswerTitle: string;
  finalAnswerBullets: string[];
  logs: string[];
  rawTrace?: Record<string, unknown>;
  replay?: Record<string, unknown>;
  runtimeConfig?: Record<string, unknown>;
}

export interface EvidenceChain {
  question: string;
  retrievalMethod: string;
  retrievedChunks: EvidenceChunk[];
  usedContext: string;
  answerReference: {
    usedChunkCount?: number;
    sources?: string[];
    summary?: string;
  };
}

export interface EvidenceChunk {
  rank: number;
  usedByGenerator: boolean;
  score: number;
  source: string;
  metadata: RagEvidence['metadata'];
  content: string;
}

export interface ToolParam {
  name: string;
  type: string;
  description: string;
  required?: boolean;
}

export interface ToolDefinition {
  name: string;
  description: string;
  params: ToolParam[];
  status: 'available' | 'mock' | 'disabled';
  lastCall: string;
  useCase: string;
}

export interface RagEvidence {
  source: string;
  score: number;
  content?: string;
  excerpt?: string;
  chunk?: string;
  metadata: string | Record<string, string | number | boolean>;
}

export interface MemoryItem {
  id: string;
  kind: 'session' | 'summary' | 'context' | 'short' | 'long' | 'preference';
  title: string;
  content: string;
  source: string;
  updatedAt: string;
}

export interface EvaluationMetric {
  name: string;
  value: number;
  unit: string;
  trend: 'up' | 'down' | 'flat';
  note: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  type: string;
  chunks: number;
  score: number;
  updatedAt: string;
  preview: string;
}

export interface ContextSource {
  name: string;
  detail: string;
  active: boolean;
}
