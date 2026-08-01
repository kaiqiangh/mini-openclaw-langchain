import type {
  AgentBulkDeleteResult,
  AgentBulkExportResult,
  AgentBulkRuntimePatchResult,
  AgentMeta,
  DelegateDetail,
  DelegateSummary,
  SessionMeta,
} from "@/lib/api";
import type { DelegateViewModel } from "@/lib/delegates";

export type ChatToolCall = {
  tool: string;
  input?: unknown;
  output?: unknown;
};

export type RetrievalItem = {
  text: string;
  score: number;
  source: string;
};

export type ChatDebugEvent = {
  id: string;
  type: string;
  timestamp: number;
  data: unknown;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestampMs: number | null;
  toolCalls: ChatToolCall[];
  selectedSkills: string[];
  skillUses: string[];
  retrievals: RetrievalItem[];
  debugEvents: ChatDebugEvent[];
};

export type MaxStepsPromptState = {
  sessionId: string;
  message: string;
  runId?: string;
};

export type AppState = {
  initialized: boolean;
  ragEnabled: boolean;
  agents: AgentMeta[];
  currentAgentId: string;
  sessionsScope: "active" | "archived";
  sessions: SessionMeta[];
  currentSessionId: string | null;
  messages: ChatMessage[];
  isStreaming: boolean;
  selectedFilePath: string;
  selectedFileContent: string;
  fileDirty: boolean;
  error: string | null;
  maxStepsPrompt: MaxStepsPromptState | null;
  delegates: DelegateViewModel[];
  setDelegates: (delegates: DelegateViewModel[]) => void;
  reloadAgents: () => Promise<void>;
  setCurrentAgent: (agentId: string) => Promise<void>;
  createAgentById: (agentId: string) => Promise<void>;
  deleteAgentById: (agentId: string) => Promise<void>;
  bulkDeleteAgents: (agentIds: string[]) => Promise<AgentBulkDeleteResult>;
  bulkExportAgents: (agentIds: string[]) => Promise<AgentBulkExportResult>;
  bulkPatchRuntime: (
    agentIds: string[],
    patch: Record<string, unknown>,
    mode?: "merge" | "replace",
  ) => Promise<AgentBulkRuntimePatchResult>;
  setSelectedFilePath: (path: string) => Promise<void>;
  updateSelectedFileContent: (content: string) => void;
  saveSelectedFile: () => Promise<void>;
  toggleRag: (enabled: boolean) => Promise<void>;
  setSessionsScope: (scope: "active" | "archived") => Promise<void>;
  archiveSessionById: (sessionId: string) => Promise<void>;
  restoreSessionById: (sessionId: string) => Promise<void>;
  deleteSessionById: (sessionId: string, archived?: boolean) => Promise<void>;
  createNewSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  openSessionInWorkspace: (params: {
    agentId: string;
    sessionId: string;
    scope?: "active" | "archived";
  }) => Promise<void>;
  sendMessage: (content: string) => Promise<boolean>;
  continueAfterMaxSteps: () => Promise<boolean>;
  cancelAfterMaxSteps: () => Promise<void>;
};

export type AppViewSnapshot = {
  currentAgentId: string;
  sessionsScope: "active" | "archived";
  sessions: SessionMeta[];
  currentSessionId: string | null;
  messages: ChatMessage[];
  isStreaming: boolean;
  delegates: DelegateViewModel[];
  selectedFilePath: string;
  selectedFileContent: string;
  fileDirty: boolean;
  ragEnabled: boolean;
};

export function genId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

export function normalizeTimestampMs(value: unknown): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

export function mapHistoryMessage(
  sessionId: string,
  msg: {
    role: "user" | "assistant";
    content: string;
    timestamp_ms?: number;
    tool_calls?: Array<{ tool: string; input?: unknown; output?: unknown }>;
    selected_skills?: string[];
    skill_uses?: string[];
    streaming?: boolean;
    run_id?: string;
  },
  idx: number,
): ChatMessage {
  const base: ChatMessage = {
    id: `${sessionId}-${idx}`,
    role: msg.role,
    content: msg.content,
    timestampMs: normalizeTimestampMs(msg.timestamp_ms),
    toolCalls: msg.tool_calls ?? [],
    selectedSkills: msg.selected_skills ?? [],
    skillUses: msg.skill_uses ?? [],
    retrievals: [],
    debugEvents: [],
  };
  if (!msg.streaming) {
    return base;
  }
  return appendDebugEvent(base, "streaming_recovery", {
    run_id: msg.run_id ?? "",
  });
}

export function createAssistantMessage(
  timestampMs: number | null = Date.now(),
): ChatMessage {
  return {
    id: genId("assistant"),
    role: "assistant",
    content: "",
    timestampMs,
    toolCalls: [],
    selectedSkills: [],
    skillUses: [],
    retrievals: [],
    debugEvents: [],
  };
}

export function mergeUniqueStrings(
  existing: string[],
  additions: unknown,
): string[] {
  if (!Array.isArray(additions) || additions.length === 0) {
    return existing;
  }
  const seen = new Set(existing);
  const next = [...existing];
  for (const item of additions) {
    const normalized = String(item ?? "").trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    next.push(normalized);
    seen.add(normalized);
  }
  return next;
}

export function appendDebugEvent(
  message: ChatMessage,
  type: string,
  data: unknown,
): ChatMessage {
  if (message.role !== "assistant") {
    return message;
  }
  const nextEvent: ChatDebugEvent = {
    id: genId("dbg"),
    type,
    timestamp: Date.now(),
    data,
  };
  const previous = message.debugEvents[message.debugEvents.length - 1];
  if (
    previous &&
    previous.type === nextEvent.type &&
    JSON.stringify(previous.data) === JSON.stringify(data)
  ) {
    return message;
  }
  return { ...message, debugEvents: [...message.debugEvents, nextEvent] };
}

export function splitDelegateViewModels(delegates: DelegateViewModel[]): {
  summaries: DelegateSummary[];
  details: Record<string, DelegateDetail>;
} {
  const details: Record<string, DelegateDetail> = {};
  const summaries = delegates.map((delegate) => {
    const { detail, ...summary } = delegate;
    if (detail) {
      details[delegate.delegate_id] = detail;
    }
    return summary;
  });
  return { summaries, details };
}

export function areDelegateSummariesEqual(
  left: DelegateSummary[],
  right: DelegateSummary[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((delegate, index) => {
    const other = right[index];
    return (
      other !== undefined &&
      delegate.delegate_id === other.delegate_id &&
      delegate.role === other.role &&
      delegate.task === other.task &&
      delegate.status === other.status &&
      delegate.sub_session_id === other.sub_session_id &&
      delegate.created_at === other.created_at
    );
  });
}

export function buildDelegateDetailFallback(
  delegate: DelegateSummary,
  agentId: string,
  sessionId: string,
  attemptCount: number,
): DelegateDetail {
  const fallbackMessage = `Unable to load delegate detail after ${attemptCount} attempts.`;
  return {
    ...delegate,
    agent_id: agentId,
    parent_session_id: sessionId,
    allowed_tools: [],
    ...(delegate.status === "failed" || delegate.status === "timeout"
      ? { error_message: fallbackMessage }
      : {
          result_summary:
            "Delegate completed, but the detailed result could not be loaded.",
        }),
  };
}

export function isMaxStepsError(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;
  const code = String((payload as { code?: unknown }).code ?? "").toLowerCase();
  if (code === "max_steps_reached") return true;
  const error = String(
    (payload as { error?: unknown }).error ?? "",
  ).toLowerCase();
  return (
    error.includes("recursion limit") ||
    error.includes("max steps") ||
    error.includes("max_steps")
  );
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
