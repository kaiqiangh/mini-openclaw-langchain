"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  AgentBulkDeleteResult,
  AgentBulkExportResult,
  AgentBulkRuntimePatchResult,
  AgentMeta,
  archiveSession,
  bulkDeleteAgentWorkspaces,
  bulkExportAgentWorkspaces,
  bulkPatchAgentRuntime,
  createAgentWorkspace,
  createSession,
  deleteAgentWorkspace,
  deleteSession,
  generateSessionTitle,
  getAgents,
  getRagMode,
  getSessionHistory,
  getSessions,
  listDelegates,
  readWorkspaceFile,
  restoreSession,
  saveWorkspaceFile,
  SessionMeta,
  setRagMode,
  streamChat,
  type DelegateSummary,
} from "@/lib/api";

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

type AppState = {
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
  delegates: DelegateSummary[];
  setDelegates: (delegates: DelegateSummary[]) => void;
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

const AppContext = createContext<AppState | null>(null);
const CURRENT_AGENT_STORAGE_KEY = "mini-openclaw:current-agent:v1";

function genId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function readStoredCurrentAgentId(): string {
  if (typeof window === "undefined") {
    return "default";
  }
  const stored = window.localStorage.getItem(CURRENT_AGENT_STORAGE_KEY) ?? "";
  return stored.trim() || "default";
}

function normalizeTimestampMs(value: unknown): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function mapHistoryMessage(
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

function createAssistantMessage(
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

function mergeUniqueStrings(existing: string[], additions: unknown): string[] {
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

function appendDebugEvent(
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

function isMaxStepsError(payload: unknown): boolean {
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

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [initialized, setInitialized] = useState(false);
  const [ragEnabled, setRagEnabledState] = useState(false);
  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [currentAgentId, setCurrentAgentId] = useState(
    readStoredCurrentAgentId,
  );
  const [sessionsScope, setSessionsScopeState] = useState<
    "active" | "archived"
  >("active");
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [selectedFilePath, setSelectedFilePathState] =
    useState("memory/MEMORY.md");
  const [selectedFileContent, setSelectedFileContent] = useState("");
  const [fileDirty, setFileDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [maxStepsPrompt, setMaxStepsPrompt] =
    useState<MaxStepsPromptState | null>(null);
  const [delegates, setDelegatesState] = useState<DelegateSummary[]>([]);
  const agentSwitchEpochRef = useRef(0);
  const streamEpochRef = useRef(0);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamConnectionRef = useRef(false);

  const cancelActiveStream = useCallback(() => {
    streamEpochRef.current += 1;
    const controller = streamAbortRef.current;
    streamAbortRef.current = null;
    if (controller && !controller.signal.aborted) {
      controller.abort();
    }
    streamConnectionRef.current = false;
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(CURRENT_AGENT_STORAGE_KEY, currentAgentId);
  }, [currentAgentId]);

  const refreshAgents = useCallback(async () => {
    const next = await getAgents();
    setAgents(next);
    return next;
  }, []);

  const refreshSessions = useCallback(
    async (scopeOverride?: "active" | "archived", agentIdOverride?: string) => {
      const effectiveScope = scopeOverride ?? sessionsScope;
      const effectiveAgentId = agentIdOverride ?? currentAgentId;
      const next = await getSessions(effectiveScope, effectiveAgentId);
      setSessions(next);
      return next;
    },
    [currentAgentId, sessionsScope],
  );

  const loadSession = useCallback(
    async (sessionId: string, archived = false, agentId: string) => {
      const history = await getSessionHistory(sessionId, archived, agentId);
      const mapped: ChatMessage[] = history.messages.map((msg, idx) =>
        mapHistoryMessage(sessionId, msg, idx),
      );
      const hasStreaming = history.messages.some((msg) =>
        Boolean(msg.streaming),
      );
      setDelegatesState([]);
      setMessages(mapped);
      setCurrentSessionId(sessionId);
      setIsStreaming(hasStreaming);
    },
    [],
  );

  const setCurrentAgent = useCallback(
    async (agentId: string) => {
      if (agentId === currentAgentId) return;
      cancelActiveStream();
      const switchEpoch = agentSwitchEpochRef.current + 1;
      agentSwitchEpochRef.current = switchEpoch;
      setError(null);
      setCurrentAgentId(agentId);
      setSessionsScopeState("active");
      setSessions([]);
      setCurrentSessionId(null);
      setDelegatesState([]);
      setMessages([]);
      setIsStreaming(false);
      setSelectedFilePathState("memory/MEMORY.md");
      setSelectedFileContent("");
      setFileDirty(false);

      try {
        const rag = await getRagMode(agentId);
        if (agentSwitchEpochRef.current !== switchEpoch) return;
        setRagEnabledState(rag);

        const list = await refreshSessions("active", agentId);
        if (agentSwitchEpochRef.current !== switchEpoch) return;
        if (list.length > 0) {
          await loadSession(list[0].session_id, false, agentId);
          if (agentSwitchEpochRef.current !== switchEpoch) return;
        }
        const initialContent = await readWorkspaceFile(
          "memory/MEMORY.md",
          agentId,
        );
        if (agentSwitchEpochRef.current !== switchEpoch) return;
        setSelectedFilePathState("memory/MEMORY.md");
        setSelectedFileContent(initialContent);
        setFileDirty(false);
      } catch (err) {
        if (agentSwitchEpochRef.current !== switchEpoch) return;
        setError(err instanceof Error ? err.message : "Failed to switch agent");
      }
    },
    [cancelActiveStream, currentAgentId, loadSession, refreshSessions],
  );

  const createAgentById = useCallback(
    async (agentId: string) => {
      const normalized = agentId.trim();
      if (!normalized) return;
      setError(null);
      await createAgentWorkspace(normalized);
      await refreshAgents();
      await setCurrentAgent(normalized);
    },
    [refreshAgents, setCurrentAgent],
  );

  const deleteAgentById = useCallback(
    async (agentId: string) => {
      if (agentId === "default") {
        setError("Default agent cannot be deleted.");
        return;
      }
      setError(null);
      await deleteAgentWorkspace(agentId);
      const next = await refreshAgents();
      const fallback =
        next.find((item) => item.agent_id === "default")?.agent_id ??
        next[0]?.agent_id ??
        "default";
      await setCurrentAgent(fallback);
    },
    [refreshAgents, setCurrentAgent],
  );

  const reloadAgents = useCallback(async () => {
    setError(null);
    await refreshAgents();
  }, [refreshAgents]);

  const bulkDeleteAgents = useCallback(
    async (agentIds: string[]) => {
      setError(null);
      const normalized = Array.from(
        new Set(agentIds.map((item) => item.trim()).filter(Boolean)),
      );
      const result = await bulkDeleteAgentWorkspaces(normalized);
      const next = await refreshAgents();
      if (!next.some((item) => item.agent_id === currentAgentId)) {
        const fallback =
          next.find((item) => item.agent_id === "default")?.agent_id ??
          next[0]?.agent_id ??
          "default";
        await setCurrentAgent(fallback);
      }
      return result;
    },
    [currentAgentId, refreshAgents, setCurrentAgent],
  );

  const bulkExportAgents = useCallback(async (agentIds: string[]) => {
    setError(null);
    const normalized = Array.from(
      new Set(agentIds.map((item) => item.trim()).filter(Boolean)),
    );
    return bulkExportAgentWorkspaces(normalized);
  }, []);

  const bulkPatchRuntime = useCallback(
    async (
      agentIds: string[],
      patch: Record<string, unknown>,
      mode: "merge" | "replace" = "merge",
    ) => {
      setError(null);
      const normalized = Array.from(
        new Set(agentIds.map((item) => item.trim()).filter(Boolean)),
      );
      return bulkPatchAgentRuntime(normalized, patch, mode);
    },
    [],
  );

  const createNewSession = useCallback(async () => {
    setError(null);
    setSessionsScopeState("active");
    const created = await createSession(undefined, currentAgentId);
    await refreshSessions("active", currentAgentId);
    setCurrentSessionId(created.session_id);
    setMessages([]);
  }, [currentAgentId, refreshSessions]);

  const selectSession = useCallback(
    async (sessionId: string) => {
      setError(null);
      await loadSession(
        sessionId,
        sessionsScope === "archived",
        currentAgentId,
      );
    },
    [currentAgentId, loadSession, sessionsScope],
  );

  const openSessionInWorkspace = useCallback(
    async ({
      agentId,
      sessionId,
      scope = "active",
    }: {
      agentId: string;
      sessionId: string;
      scope?: "active" | "archived";
    }) => {
      const nextAgentId = agentId.trim() || "default";
      const nextScope = scope === "archived" ? "archived" : "active";
      cancelActiveStream();
      const switchEpoch = agentSwitchEpochRef.current + 1;
      agentSwitchEpochRef.current = switchEpoch;
      setError(null);
      setSessionsScopeState(nextScope);
      setSessions([]);
      setCurrentSessionId(null);
      setMessages([]);
      setIsStreaming(false);

      const switchingAgent = nextAgentId !== currentAgentId;
      if (switchingAgent) {
        setCurrentAgentId(nextAgentId);
        setSelectedFilePathState("memory/MEMORY.md");
        setSelectedFileContent("");
        setFileDirty(false);
      }

      try {
        if (switchingAgent) {
          const rag = await getRagMode(nextAgentId);
          if (agentSwitchEpochRef.current !== switchEpoch) return;
          setRagEnabledState(rag);
        }

        const list = await getSessions(nextScope, nextAgentId);
        if (agentSwitchEpochRef.current !== switchEpoch) return;
        setSessions(list);

        await loadSession(sessionId, nextScope === "archived", nextAgentId);
        if (agentSwitchEpochRef.current !== switchEpoch) return;

        if (switchingAgent) {
          const initialContent = await readWorkspaceFile(
            "memory/MEMORY.md",
            nextAgentId,
          );
          if (agentSwitchEpochRef.current !== switchEpoch) return;
          setSelectedFilePathState("memory/MEMORY.md");
          setSelectedFileContent(initialContent);
          setFileDirty(false);
        }
      } catch (err) {
        if (agentSwitchEpochRef.current !== switchEpoch) return;
        const message =
          err instanceof Error ? err.message : "Failed to open workspace session";
        setError(message);
        throw err instanceof Error ? err : new Error(message);
      }
    },
    [cancelActiveStream, currentAgentId, loadSession],
  );

  const setSelectedFilePath = useCallback(
    async (path: string) => {
      if (path === selectedFilePath) return;
      if (
        fileDirty &&
        typeof window !== "undefined" &&
        !window.confirm("Discard unsaved file changes and switch files?")
      ) {
        return;
      }
      setError(null);
      const content = await readWorkspaceFile(path, currentAgentId);
      setSelectedFilePathState(path);
      setSelectedFileContent(content);
      setFileDirty(false);
    },
    [currentAgentId, fileDirty, selectedFilePath],
  );

  const updateSelectedFileContent = useCallback((content: string) => {
    setSelectedFileContent(content);
    setFileDirty(true);
  }, []);

  const saveSelectedFile = useCallback(async () => {
    setError(null);
    await saveWorkspaceFile(
      selectedFilePath,
      selectedFileContent,
      currentAgentId,
    );
    setFileDirty(false);
  }, [currentAgentId, selectedFileContent, selectedFilePath]);

  const toggleRag = useCallback(
    async (enabled: boolean) => {
      setError(null);
      const next = await setRagMode(enabled, currentAgentId);
      setRagEnabledState(next);
    },
    [currentAgentId],
  );

  const setSessionsScope = useCallback(
    async (scope: "active" | "archived") => {
      setError(null);
      if (scope === "archived") {
        cancelActiveStream();
      }
      setSessionsScopeState(scope);
      if (scope === "archived") {
        setIsStreaming(false);
      }
      const list = await refreshSessions(scope, currentAgentId);
      if (list.length > 0) {
        await loadSession(
          list[0].session_id,
          scope === "archived",
          currentAgentId,
        );
      } else {
        setCurrentSessionId(null);
        setMessages([]);
      }
    },
    [cancelActiveStream, currentAgentId, loadSession, refreshSessions],
  );

  const archiveSessionById = useCallback(
    async (sessionId: string) => {
      setError(null);
      await archiveSession(sessionId, currentAgentId);
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
      await refreshSessions("active", currentAgentId);
    },
    [currentAgentId, currentSessionId, refreshSessions],
  );

  const restoreSessionById = useCallback(
    async (sessionId: string) => {
      setError(null);
      await restoreSession(sessionId, currentAgentId);
      await refreshSessions("archived", currentAgentId);
    },
    [currentAgentId, refreshSessions],
  );

  const deleteSessionById = useCallback(
    async (sessionId: string, archived = false) => {
      setError(null);
      await deleteSession(sessionId, archived, currentAgentId);
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
      await refreshSessions(archived ? "archived" : "active", currentAgentId);
    },
    [currentAgentId, currentSessionId, refreshSessions],
  );

  const runStreamTurn = useCallback(
    async ({
      message,
      resumeSameTurn = false,
      seedUserMessage = true,
      sessionIdOverride,
    }: {
      message: string;
      resumeSameTurn?: boolean;
      seedUserMessage?: boolean;
      sessionIdOverride?: string;
    }): Promise<boolean> => {
      const trimmed = message.trim();
      if (!trimmed || isStreaming) return false;
      if (!resumeSameTurn && sessionsScope === "archived") {
        setError(
          "Archived sessions are read-only. Restore the session to continue chatting.",
        );
        return false;
      }

      const streamEpoch = streamEpochRef.current + 1;
      streamEpochRef.current = streamEpoch;
      const streamAbortController = new AbortController();
      streamAbortRef.current?.abort();
      streamAbortRef.current = streamAbortController;
      const streamAgentId = currentAgentId;
      const isCurrentStream = () =>
        streamEpochRef.current === streamEpoch &&
        !streamAbortController.signal.aborted;

      setError(null);
      setMaxStepsPrompt(null);
      setIsStreaming(true);
      streamConnectionRef.current = true;
      let activeSessionId = sessionIdOverride ?? currentSessionId;

      try {
        let sessionId = sessionIdOverride ?? currentSessionId;
        if (!sessionId) {
          if (resumeSameTurn) {
            throw new Error("Cannot continue: no active session is available.");
          }
          const created = await createSession(undefined, streamAgentId);
          if (!isCurrentStream()) return false;
          sessionId = created.session_id;
          activeSessionId = created.session_id;
          setCurrentSessionId(sessionId);
          await refreshSessions(undefined, streamAgentId);
          if (!isCurrentStream()) return false;
        }

        if (!isCurrentStream()) return false;
        if (seedUserMessage) {
          const userMessage: ChatMessage = {
            id: genId("user"),
            role: "user",
            content: trimmed,
            timestampMs: Date.now(),
            toolCalls: [],
            selectedSkills: [],
            skillUses: [],
            retrievals: [],
            debugEvents: [],
          };
          const assistantMessage = createAssistantMessage();
          setMessages((prev) => [...prev, userMessage, assistantMessage]);
        } else {
          setMessages((prev) => {
            if (prev.length === 0) return [createAssistantMessage()];
            const next = [...prev];
            const last = next[next.length - 1];
            if (!last || last.role !== "assistant") {
              next.push(createAssistantMessage());
              return next;
            }
            const hasContent =
              Boolean(last.content.trim()) ||
              last.toolCalls.length > 0 ||
              last.selectedSkills.length > 0 ||
              last.retrievals.length > 0 ||
              last.debugEvents.length > 0;
            if (hasContent) {
              next.push(createAssistantMessage());
            }
            return next;
          });
        }

        await streamChat(
          trimmed,
          sessionId,
          ({ event, data }) => {
            if (!isCurrentStream()) return;
            let parsed: unknown = data;
            try {
              parsed = data ? JSON.parse(data) : {};
            } catch {
              parsed = { raw: data };
            }

            setMessages((prev) => {
              if (prev.length === 0) return prev;
              const next = [...prev];
              const idx = next.length - 1;
              const active = next[idx];
              if (!active || active.role !== "assistant") return prev;

              if (event === "token") {
                const piece =
                  typeof parsed === "object" && parsed !== null
                    ? (parsed as { content?: string }).content
                    : "";
                next[idx] = {
                  ...active,
                  content: active.content + (piece ?? ""),
                };
                return next;
              }

              if (event === "retrieval") {
                const retrievals =
                  typeof parsed === "object" && parsed !== null
                    ? ((parsed as { results?: RetrievalItem[] }).results ?? [])
                    : [];
                next[idx] = appendDebugEvent(
                  { ...active, retrievals },
                  "retrieval",
                  parsed,
                );
                return next;
              }

              if (event === "tool_start") {
                const payload =
                  (parsed as {
                    tool?: string;
                    input?: unknown;
                    skill_uses?: string[];
                  }) ?? {};
                next[idx] = appendDebugEvent(
                  {
                    ...active,
                    toolCalls: [
                      ...active.toolCalls,
                      { tool: payload.tool ?? "tool", input: payload.input },
                    ],
                    skillUses: mergeUniqueStrings(
                      active.skillUses,
                      payload.skill_uses,
                    ),
                  },
                  "tool_start",
                  payload,
                );
                return next;
              }

              if (event === "selected_skills") {
                const payload =
                  (parsed as {
                    skills?: Array<{ name?: string } | string>;
                  }) ?? {};
                const selectedSkills = mergeUniqueStrings(
                  active.selectedSkills,
                  Array.isArray(payload.skills)
                    ? payload.skills.map((item) =>
                        typeof item === "string" ? item : item?.name ?? "",
                      )
                    : [],
                );
                next[idx] = appendDebugEvent(
                  {
                    ...active,
                    selectedSkills,
                  },
                  "selected_skills",
                  payload,
                );
                return next;
              }

              if (event === "tool_end") {
                const payload =
                  (parsed as {
                    output?: unknown;
                    tool?: string;
                    skill_uses?: string[];
                  }) ?? {};
                const toolCalls = [...active.toolCalls];
                if (toolCalls.length > 0) {
                  toolCalls[toolCalls.length - 1] = {
                    ...toolCalls[toolCalls.length - 1],
                    output: payload.output,
                  };
                }
                next[idx] = appendDebugEvent(
                  {
                    ...active,
                    toolCalls,
                    skillUses: mergeUniqueStrings(
                      active.skillUses,
                      payload.skill_uses,
                    ),
                  },
                  "tool_end",
                  payload,
                );
                return next;
              }

              if (
                event === "run_start" ||
                event === "agent_update" ||
                event === "reasoning" ||
                event === "usage"
              ) {
                next[idx] = appendDebugEvent(active, event, parsed);
                return next;
              }

              if (event === "new_response") {
                const hasContent =
                  Boolean(active.content.trim()) ||
                  active.toolCalls.length > 0 ||
                  active.selectedSkills.length > 0 ||
                  active.retrievals.length > 0 ||
                  active.debugEvents.length > 0;
                if (hasContent) {
                  next.push(createAssistantMessage());
                }
                return next;
              }

              if (event === "done") {
                const payload =
                  (parsed as {
                    content?: string;
                    run_id?: string;
                    token_source?: string;
                  }) ?? {};
                const finalContent = payload.content ?? "";
                let updated = active;
                if (!updated.content && finalContent) {
                  updated = { ...updated, content: finalContent };
                }
                next[idx] = appendDebugEvent(updated, "done", payload);
                return next;
              }

              if (event === "error") {
                next[idx] = appendDebugEvent(active, "error", parsed);
                return next;
              }

              return next;
            });

            if (event === "title" || event === "done") {
              void refreshSessions("active", streamAgentId);
            }
            if (event === "error") {
              const messageText =
                typeof parsed === "object" && parsed !== null
                  ? ((parsed as { error?: string }).error ??
                    "Unknown stream error")
                  : "Unknown stream error";
              if (isMaxStepsError(parsed) && activeSessionId) {
                const runId =
                  typeof parsed === "object" && parsed !== null
                    ? String((parsed as { run_id?: unknown }).run_id ?? "")
                    : "";
                setMaxStepsPrompt({
                  sessionId: activeSessionId,
                  message: trimmed,
                  ...(runId ? { runId } : {}),
                });
                setError("Agent reached max_steps. Continue or cancel.");
              } else {
                setError(messageText);
              }
            }
          },
          streamAgentId,
          resumeSameTurn,
          streamAbortController.signal,
        );
        return true;
      } catch (err) {
        if (!isCurrentStream() || isAbortError(err)) {
          return false;
        }
        setError(err instanceof Error ? err.message : "Failed to send message");
        return false;
      } finally {
        if (streamAbortRef.current === streamAbortController) {
          streamAbortRef.current = null;
        }
        if (isCurrentStream()) {
          streamConnectionRef.current = false;
          try {
            if (activeSessionId) {
              const finalSessionId = activeSessionId;
              const refreshed = await getSessionHistory(
                finalSessionId,
                false,
                streamAgentId,
              );
              if (isCurrentStream()) {
                const mapped: ChatMessage[] = refreshed.messages.map(
                  (msg, idx) => ({
                    ...mapHistoryMessage(finalSessionId, msg, idx),
                  }),
                );
                setMessages(mapped);
                const hasStreaming = refreshed.messages.some((item) =>
                  Boolean(item.streaming),
                );
                setIsStreaming(hasStreaming);
              }
            } else {
              setIsStreaming(false);
            }
          } catch {
            if (isCurrentStream()) {
              setIsStreaming(false);
            }
          }
        }
      }
    },
    [
        currentAgentId,
        currentSessionId,
        isStreaming,
        refreshSessions,
        sessionsScope,
    ],
  );

  const sendMessage = useCallback(
    async (content: string) => {
      return runStreamTurn({
        message: content,
        resumeSameTurn: false,
        seedUserMessage: true,
      });
    },
    [runStreamTurn],
  );

  const continueAfterMaxSteps = useCallback(async () => {
    if (!maxStepsPrompt) return false;
    return runStreamTurn({
      message: maxStepsPrompt.message,
      sessionIdOverride: maxStepsPrompt.sessionId,
      resumeSameTurn: true,
      seedUserMessage: false,
    });
  }, [maxStepsPrompt, runStreamTurn]);

  const cancelAfterMaxSteps = useCallback(async () => {
    if (!maxStepsPrompt) return;
    const targetSessionId = maxStepsPrompt.sessionId;
    setMaxStepsPrompt(null);
    cancelActiveStream();
    setIsStreaming(false);
    setError(null);
    try {
      await generateSessionTitle(targetSessionId, currentAgentId);
    } catch {
      // Best-effort title generation only.
    }
    await refreshSessions("active", currentAgentId);
    if (currentSessionId === targetSessionId) {
      await loadSession(targetSessionId, false, currentAgentId);
    }
  }, [
    currentAgentId,
    cancelActiveStream,
    currentSessionId,
    loadSession,
    maxStepsPrompt,
    refreshSessions,
  ]);

  useEffect(() => {
    if (!initialized) return;
    if (!currentSessionId) return;
    if (sessionsScope === "archived") return;
    if (!isStreaming) return;
    if (streamConnectionRef.current) return;

    let cancelled = false;

    const poll = async () => {
      try {
        const history = await getSessionHistory(
          currentSessionId,
          false,
          currentAgentId,
        );
        if (cancelled) return;

        const mapped: ChatMessage[] = history.messages.map((msg, idx) =>
          mapHistoryMessage(currentSessionId, msg, idx),
        );
        const hasStreaming = history.messages.some((msg) =>
          Boolean(msg.streaming),
        );
        setMessages(mapped);
        setIsStreaming(hasStreaming);
        if (!hasStreaming) {
          void refreshSessions("active", currentAgentId);
        }
      } catch {
        // Keep background polling best-effort only.
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 1500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    currentAgentId,
    currentSessionId,
    initialized,
    isStreaming,
    refreshSessions,
    sessionsScope,
  ]);

  useEffect(() => {
    if (!initialized) return;
    if (!currentSessionId) {
      setDelegatesState([]);
      return;
    }
    if (sessionsScope === "archived") {
      setDelegatesState([]);
      return;
    }

    let cancelled = false;

    const pollDelegates = async () => {
      try {
        const response = await listDelegates(currentAgentId, currentSessionId);
        if (cancelled) return;
        setDelegatesState(response.delegates);
      } catch (error) {
        if (cancelled) return;
        setDelegatesState([]);
        console.warn("Failed to poll delegates", error);
      }
    };

    void pollDelegates();
    const timer = window.setInterval(() => {
      void pollDelegates();
    }, isStreaming ? 1500 : 2500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    currentAgentId,
    currentSessionId,
    initialized,
    isStreaming,
    sessionsScope,
  ]);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        const listedAgents = await refreshAgents();
        if (cancelled) return;

        let effectiveAgents = listedAgents;
        if (effectiveAgents.length === 0) {
          await createAgentWorkspace("default");
          effectiveAgents = await refreshAgents();
        }

        const selected =
          effectiveAgents.find((item) => item.agent_id === currentAgentId)
            ?.agent_id ??
          effectiveAgents.find((item) => item.agent_id === "default")
            ?.agent_id ??
          effectiveAgents[0]?.agent_id ??
          "default";
        setCurrentAgentId(selected);

        const rag = await getRagMode(selected);
        if (cancelled) return;
        setRagEnabledState(rag);

        const nextSessions = await getSessions("active", selected);
        if (cancelled) return;
        setSessions(nextSessions);

        if (nextSessions.length > 0) {
          await loadSession(nextSessions[0].session_id, false, selected);
        } else {
          const created = await createSession(undefined, selected);
          if (cancelled) return;
          setCurrentSessionId(created.session_id);
          setMessages([]);
          const refreshed = await getSessions("active", selected);
          if (cancelled) return;
          setSessions(refreshed);
        }

        const initialContent = await readWorkspaceFile(
          "memory/MEMORY.md",
          selected,
        );
        if (cancelled) return;
        setSelectedFilePathState("memory/MEMORY.md");
        setSelectedFileContent(initialContent);
        setFileDirty(false);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Initialization failed",
          );
        }
      } finally {
        if (!cancelled) {
          setInitialized(true);
        }
      }
    }

    void boot();

    return () => {
      cancelled = true;
    };
  }, [loadSession, refreshAgents]);

  const value = useMemo<AppState>(
    () => ({
      initialized,
      ragEnabled,
      agents,
      currentAgentId,
      sessionsScope,
      sessions,
      currentSessionId,
      messages,
      isStreaming,
      selectedFilePath,
      selectedFileContent,
      fileDirty,
      error,
      maxStepsPrompt,
      delegates,
      setDelegates: setDelegatesState,
      reloadAgents,
      setCurrentAgent,
      createAgentById,
      deleteAgentById,
      bulkDeleteAgents,
      bulkExportAgents,
      bulkPatchRuntime,
      setSelectedFilePath,
      updateSelectedFileContent,
      saveSelectedFile,
      toggleRag,
      setSessionsScope,
      archiveSessionById,
      restoreSessionById,
      deleteSessionById,
      createNewSession,
      selectSession,
      openSessionInWorkspace,
      sendMessage,
      continueAfterMaxSteps,
      cancelAfterMaxSteps,
    }),
    [
      initialized,
      ragEnabled,
      agents,
      currentAgentId,
      sessionsScope,
      sessions,
      currentSessionId,
      messages,
      isStreaming,
      selectedFilePath,
      selectedFileContent,
      fileDirty,
      error,
      maxStepsPrompt,
      delegates,
      setDelegatesState,
      reloadAgents,
      setCurrentAgent,
      createAgentById,
      deleteAgentById,
      bulkDeleteAgents,
      bulkExportAgents,
      bulkPatchRuntime,
      setSelectedFilePath,
      updateSelectedFileContent,
      saveSelectedFile,
      toggleRag,
      setSessionsScope,
      archiveSessionById,
      restoreSessionById,
      deleteSessionById,
      createNewSession,
      selectSession,
      openSessionInWorkspace,
      sendMessage,
      continueAfterMaxSteps,
      cancelAfterMaxSteps,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppStore(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useAppStore must be used within AppProvider");
  }
  return ctx;
}
