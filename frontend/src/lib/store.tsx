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
  AgentMeta,
  archiveSession,
  createAgentWorkspace,
  createSession,
  deleteAgentWorkspace,
  deleteSession,
  getAgents,
  getRagMode,
  getSessionHistory,
  getSessions,
  readWorkspaceFile,
  restoreSession,
  saveWorkspaceFile,
  SessionMeta,
  setRagMode,
  streamChat,
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
  toolCalls: ChatToolCall[];
  retrievals: RetrievalItem[];
  debugEvents: ChatDebugEvent[];
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
  setCurrentAgent: (agentId: string) => Promise<void>;
  createAgentById: (agentId: string) => Promise<void>;
  deleteAgentById: (agentId: string) => Promise<void>;
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
  sendMessage: (content: string) => Promise<void>;
};

const AppContext = createContext<AppState | null>(null);

function genId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function createAssistantMessage(): ChatMessage {
  return {
    id: genId("assistant"),
    role: "assistant",
    content: "",
    toolCalls: [],
    retrievals: [],
    debugEvents: [],
  };
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

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [initialized, setInitialized] = useState(false);
  const [ragEnabled, setRagEnabledState] = useState(false);
  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [currentAgentId, setCurrentAgentId] = useState("default");
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
  const agentSwitchEpochRef = useRef(0);
  const streamConnectionRef = useRef(false);

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
      const mapped: ChatMessage[] = history.messages.map((msg, idx) => {
        const base: ChatMessage = {
          id: `${sessionId}-${idx}`,
          role: msg.role,
          content: msg.content,
          toolCalls: msg.tool_calls ?? [],
          retrievals: [],
          debugEvents: [],
        };
        if (!msg.streaming) {
          return base;
        }
        return appendDebugEvent(base, "streaming_recovery", {
          run_id: msg.run_id ?? "",
        });
      });
      const hasStreaming = history.messages.some((msg) => Boolean(msg.streaming));
      setMessages(mapped);
      setCurrentSessionId(sessionId);
      setIsStreaming(hasStreaming);
    },
    [],
  );

  const setCurrentAgent = useCallback(
    async (agentId: string) => {
      if (agentId === currentAgentId) return;
      const switchEpoch = agentSwitchEpochRef.current + 1;
      agentSwitchEpochRef.current = switchEpoch;
      setError(null);
      setCurrentAgentId(agentId);
      setSessionsScopeState("active");
      setSessions([]);
      setCurrentSessionId(null);
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
    [currentAgentId, loadSession, refreshSessions],
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

  const setSelectedFilePath = useCallback(
    async (path: string) => {
      setError(null);
      const content = await readWorkspaceFile(path, currentAgentId);
      setSelectedFilePathState(path);
      setSelectedFileContent(content);
      setFileDirty(false);
    },
    [currentAgentId],
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
    [currentAgentId, loadSession, refreshSessions],
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

  const sendMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim();
      if (!trimmed || isStreaming) return;
      if (sessionsScope === "archived") {
        setError(
          "Archived sessions are read-only. Restore the session to continue chatting.",
        );
        return;
      }

      setError(null);
      setIsStreaming(true);
      streamConnectionRef.current = true;
      let activeSessionId = currentSessionId;

      try {
        let sessionId = currentSessionId;
        if (!sessionId) {
          const created = await createSession(undefined, currentAgentId);
          sessionId = created.session_id;
          activeSessionId = created.session_id;
          setCurrentSessionId(sessionId);
          await refreshSessions(undefined, currentAgentId);
        }

        const userMessage: ChatMessage = {
          id: genId("user"),
          role: "user",
          content: trimmed,
          toolCalls: [],
          retrievals: [],
          debugEvents: [],
        };

        const assistantMessage = createAssistantMessage();
        setMessages((prev) => [...prev, userMessage, assistantMessage]);

        await streamChat(
          trimmed,
          sessionId,
          ({ event, data }) => {
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
                  (parsed as { tool?: string; input?: unknown }) ?? {};
                next[idx] = appendDebugEvent(
                  {
                    ...active,
                    toolCalls: [
                      ...active.toolCalls,
                      { tool: payload.tool ?? "tool", input: payload.input },
                    ],
                  },
                  "tool_start",
                  payload,
                );
                return next;
              }

              if (event === "tool_end") {
                const payload =
                  (parsed as { output?: unknown; tool?: string }) ?? {};
                const toolCalls = [...active.toolCalls];
                if (toolCalls.length > 0) {
                  toolCalls[toolCalls.length - 1] = {
                    ...toolCalls[toolCalls.length - 1],
                    output: payload.output,
                  };
                }
                next[idx] = appendDebugEvent(
                  { ...active, toolCalls },
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
              void refreshSessions("active", currentAgentId);
            }
            if (event === "error") {
              const messageText =
                typeof parsed === "object" && parsed !== null
                  ? ((parsed as { error?: string }).error ??
                    "Unknown stream error")
                  : "Unknown stream error";
              setError(messageText);
            }
          },
          currentAgentId,
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to send message");
      } finally {
        streamConnectionRef.current = false;
        try {
          if (activeSessionId) {
            const refreshed = await getSessionHistory(
              activeSessionId,
              false,
              currentAgentId,
            );
            const mapped: ChatMessage[] = refreshed.messages.map((msg, idx) => ({
              id: `${activeSessionId}-${idx}`,
              role: msg.role,
              content: msg.content,
              toolCalls: msg.tool_calls ?? [],
              retrievals: [],
              debugEvents: [],
            }));
            setMessages(mapped);
            const hasStreaming = refreshed.messages.some((item) =>
              Boolean(item.streaming),
            );
            setIsStreaming(hasStreaming);
          } else {
            setIsStreaming(false);
          }
        } catch {
          setIsStreaming(false);
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

        const mapped: ChatMessage[] = history.messages.map((msg, idx) => {
          const base: ChatMessage = {
            id: `${currentSessionId}-${idx}`,
            role: msg.role,
            content: msg.content,
            toolCalls: msg.tool_calls ?? [],
            retrievals: [],
            debugEvents: [],
          };
          if (!msg.streaming) {
            return base;
          }
          return appendDebugEvent(base, "streaming_recovery", {
            run_id: msg.run_id ?? "",
          });
        });
        const hasStreaming = history.messages.some((msg) => Boolean(msg.streaming));
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
      setCurrentAgent,
      createAgentById,
      deleteAgentById,
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
      sendMessage,
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
      setCurrentAgent,
      createAgentById,
      deleteAgentById,
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
      sendMessage,
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
