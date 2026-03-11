"use client";

import Link from "next/link";
import {
  type ReadonlyURLSearchParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import { type ReactNode, Suspense, useEffect, useMemo, useRef, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { SessionUsageSummary } from "@/components/chat/SessionUsageSummary";
import {
  Badge,
  Button,
  EmptyState,
  Input,
  Select,
  Skeleton,
  TabButton,
  TabsList,
} from "@/components/ui/primitives";
import {
  AgentMeta,
  archiveSession,
  ChatHistoryResponse,
  createSession,
  deleteSession,
  getAgents,
  getSessionHistory,
  getSessions,
  restoreSession,
  SessionMeta,
} from "@/lib/api";
import {
  ChatDebugEvent,
  ChatMessage as StoreChatMessage,
  ChatToolCall,
  RetrievalItem,
  useAppStore,
} from "@/lib/store";
import { sessionScopeTone } from "@/lib/badge-tones";

const LIVE_EDGE_THRESHOLD_PX = 80;
const detailTimestampFormatter = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

type SessionScope = "active" | "archived";
type SessionMessageView = {
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

function formatTimestamp(timestampValue: number): string {
  if (!Number.isFinite(timestampValue) || timestampValue <= 0) return "—";
  const timestampMs =
    timestampValue > 1_000_000_000_000
      ? timestampValue
      : Math.round(timestampValue * 1000);
  return detailTimestampFormatter.format(new Date(timestampMs));
}

function normalizeScope(raw: string | null): SessionScope {
  return raw === "archived" ? "archived" : "active";
}

function normalizeTimestampMs(value: unknown): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function mapHistoryMessages(history: ChatHistoryResponse): SessionMessageView[] {
  return history.messages.map((message, index) => {
    const debugEvents: ChatDebugEvent[] = [];
    if (message.streaming) {
      debugEvents.push({
        id: `${history.session_id}-${index}-streaming`,
        type: "streaming_recovery",
        timestamp: normalizeTimestampMs(message.timestamp_ms) ?? Date.now(),
        data: { run_id: message.run_id ?? "" },
      });
    }

    return {
      id: `${history.session_id}-${index}`,
      role: message.role,
      content: message.content,
      timestampMs: normalizeTimestampMs(message.timestamp_ms),
      toolCalls: message.tool_calls ?? [],
      selectedSkills: message.selected_skills ?? [],
      skillUses: message.skill_uses ?? [],
      retrievals: [],
      debugEvents,
    };
  });
}

function buildParams(
  searchParams: ReadonlyURLSearchParams,
  updates: Record<string, string | undefined>,
) {
  const params = new URLSearchParams(searchParams.toString());
  for (const [key, value] of Object.entries(updates)) {
    if (!value) {
      params.delete(key);
      continue;
    }
    params.set(key, value);
  }
  return params;
}

type TranscriptFeedProps = {
  messages: Array<SessionMessageView | StoreChatMessage>;
  loading: boolean;
  error: string;
  emptyTitle: string;
  emptyDescription: string;
  footer?: ReactNode;
};

function TranscriptFeed({
  messages,
  loading,
  error,
  emptyTitle,
  emptyDescription,
  footer,
}: TranscriptFeedProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [atLiveEdge, setAtLiveEdge] = useState(true);

  useEffect(() => {
    if (!scrollRef.current || !atLiveEdge) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [atLiveEdge, messages, loading]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        className="ui-scroll-area flex-1 px-4 pt-4"
        onScroll={(event) => {
          const node = event.currentTarget;
          const distanceFromBottom =
            node.scrollHeight - node.scrollTop - node.clientHeight;
          setAtLiveEdge(distanceFromBottom <= LIVE_EDGE_THRESHOLD_PX);
        }}
      >
        {error ? (
          <div className="ui-alert mb-3" role="alert">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : messages.length === 0 ? (
          <EmptyState title={emptyTitle} description={emptyDescription} />
        ) : (
          <div className="space-y-3">
            {messages.map((message) => (
              <ChatMessage
                key={message.id}
                role={message.role}
                content={message.content}
                timestampMs={message.timestampMs}
                toolCalls={message.toolCalls}
                selectedSkills={message.selectedSkills}
                skillUses={message.skillUses}
                retrievals={message.retrievals}
                debugEvents={message.debugEvents}
              />
            ))}
          </div>
        )}
      </div>

      {footer ? (
        <div className="border-t border-[var(--border)] px-4 pb-4 pt-3">
          {!atLiveEdge && messages.length > 0 ? (
            <div className="mb-2 flex justify-end">
              <Button
                type="button"
                size="sm"
                className="px-3"
                onClick={() => {
                  if (!scrollRef.current) return;
                  scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                  setAtLiveEdge(true);
                }}
              >
                Jump to latest
              </Button>
            </div>
          ) : null}
          {footer}
        </div>
      ) : null}
    </div>
  );
}

type LiveConversationProps = {
  messages: StoreChatMessage[];
  loading: boolean;
  error: string;
  isStreaming: boolean;
  maxStepsPrompt: unknown;
  onContinue: () => void;
  onCancel: () => void;
};

function LiveConversation({
  messages,
  loading,
  error,
  isStreaming,
  maxStepsPrompt,
  onContinue,
  onCancel,
}: LiveConversationProps) {
  return (
    <TranscriptFeed
      messages={messages}
      loading={loading}
      error={error}
      emptyTitle="No Messages Yet"
      emptyDescription="Send a message to start the session."
      footer={
        <>
          {isStreaming ? (
            <div
              className="ui-status mb-2 text-[var(--accent-strong)]"
              aria-live="polite"
            >
              Streaming response…
            </div>
          ) : null}

          {maxStepsPrompt ? (
            <div className="ui-alert mb-2" role="alert">
              <div className="font-medium">Agent reached max_steps.</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="primary" onClick={onContinue}>
                  Continue
                </Button>
                <Button type="button" size="sm" onClick={onCancel}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}
          <ChatInput />
        </>
      }
    />
  );
}

type SessionDetailProps = {
  agentId: string;
  scope: SessionScope;
  session: SessionMeta | null;
  history: ChatHistoryResponse | null;
  busyAction: string | null;
  status: string;
  onArchive: () => void;
  onRestore: () => void;
  onDelete: () => void;
  onClose?: () => void;
  children: ReactNode;
};

function SessionDetail({
  agentId,
  scope,
  session,
  history,
  busyAction,
  status,
  onArchive,
  onRestore,
  onDelete,
  onClose,
  children,
}: SessionDetailProps) {
  if (!session) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-6">
        <EmptyState
          title="Select a session"
          description="Choose a session from the inbox to review or continue the conversation."
        />
      </div>
    );
  }

  return (
    <>
      <div className="ui-panel-header">
        <div className="min-w-0">
          <h2 className="ui-panel-title truncate">{session.title || "New Session"}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
            <Badge tone={sessionScopeTone(scope)}>
              {scope === "archived" ? "Archived" : "Active"}
            </Badge>
            <Badge tone="neutral" className="ui-mono">
              Agent {agentId}
            </Badge>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {scope === "active" ? (
            <Button
              type="button"
              size="sm"
              loading={busyAction === "archive"}
              onClick={onArchive}
            >
              Archive
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              loading={busyAction === "restore"}
              onClick={onRestore}
            >
              Restore
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            variant="danger"
            loading={busyAction === "delete"}
            onClick={onDelete}
          >
            Delete
          </Button>
          {onClose ? (
            <Button type="button" size="sm" onClick={onClose}>
              Close
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="ui-scroll-area border-b border-[var(--border)] px-4 py-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Session</div>
              <div className="ui-mono mt-1 break-all text-sm">{session.session_id}</div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Created</div>
              <div className="mt-1 text-sm text-[var(--text)]">
                {formatTimestamp(session.created_at)}
              </div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Updated</div>
              <div className="mt-1 text-sm text-[var(--text)]">
                {formatTimestamp(session.updated_at)}
              </div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Related Views</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Link
                  href={`/runs?agent=${encodeURIComponent(agentId)}`}
                  className="ui-btn ui-btn-sm"
                >
                  Open Runs
                </Link>
                <Link
                  href={`/traces?agent=${encodeURIComponent(agentId)}&session=${encodeURIComponent(session.session_id)}`}
                  className="ui-btn ui-btn-sm ui-btn-ghost"
                >
                  Open Traces
                </Link>
              </div>
            </div>
          </div>

          {history?.compressed_context ? (
            <section className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Compressed Context</div>
              <pre className="ui-mono mt-2 whitespace-pre-wrap text-xs text-[var(--text)]">
                {history.compressed_context}
              </pre>
            </section>
          ) : null}

          {scope === "archived" ? (
            <div className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-2 text-sm text-[var(--muted)]">
              Archived sessions are read-only. Restore this session before continuing work.
            </div>
          ) : null}

          {status ? (
            <p className="ui-helper mt-3" aria-live="polite">
              {status}
            </p>
          ) : null}
        </div>

        {children}
      </div>
    </>
  );
}

type SessionDetailShellProps = SessionDetailProps & {
  messages: Array<SessionMessageView | StoreChatMessage>;
};

function SessionDetailShell({
  messages,
  ...props
}: SessionDetailShellProps) {
  const {
    agentId,
    scope,
    session,
    history,
    busyAction,
    status,
    onArchive,
    onRestore,
    onDelete,
    onClose,
    children,
  } = props;

  if (!session) {
    return (
      <SessionDetail
        agentId={agentId}
        scope={scope}
        session={session}
        history={history}
        busyAction={busyAction}
        status={status}
        onArchive={onArchive}
        onRestore={onRestore}
        onDelete={onDelete}
        onClose={onClose}
      >
        {children}
      </SessionDetail>
    );
  }

  return (
    <>
      <SessionDetail
        agentId={agentId}
        scope={scope}
        session={session}
        history={history}
        busyAction={busyAction}
        status={status}
        onArchive={onArchive}
        onRestore={onRestore}
        onDelete={onDelete}
        onClose={onClose}
      >
        <div className="border-b border-[var(--border)] px-4 py-4">
          <SessionUsageSummary messages={messages} />
        </div>
        {children}
      </SessionDetail>
    </>
  );
}

function SessionsPageFallback() {
  return (
    <main id="main-content" className="flex min-h-0 flex-1 flex-col p-3">
      <section className="panel-shell flex min-h-0 flex-1 flex-col">
        <div className="ui-panel-header">
          <div>
            <h1 className="ui-panel-title">Sessions</h1>
            <p className="mt-1 text-sm text-[var(--muted)]">
              Loading session inbox...
            </p>
          </div>
        </div>
        <div className="space-y-3 p-4">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </section>
    </main>
  );
}

function SessionsPageContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const {
    currentAgentId,
    currentSessionId,
    sessionsScope,
    messages: liveMessages,
    isStreaming,
    error: liveError,
    maxStepsPrompt,
    continueAfterMaxSteps,
    cancelAfterMaxSteps,
    setCurrentAgent,
    setSessionsScope,
    selectSession,
  } = useAppStore();

  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeSyncing, setActiveSyncing] = useState(false);
  const [history, setHistory] = useState<ChatHistoryResponse | null>(null);
  const [status, setStatus] = useState("");
  const [listError, setListError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const scope = normalizeScope(searchParams.get("scope"));
  const query = searchParams.get("q") ?? "";
  const requestedAgentId = (searchParams.get("agent") ?? "").trim();
  const selectedSessionId = (searchParams.get("session") ?? "").trim();
  const fallbackAgentId = currentAgentId || agents[0]?.agent_id || "default";
  const agentId =
    agents.length > 0 && requestedAgentId
      ? agents.some((agent) => agent.agent_id === requestedAgentId)
        ? requestedAgentId
        : fallbackAgentId
      : requestedAgentId || fallbackAgentId;

  const selectedSession =
    sessions.find((session) => session.session_id === selectedSessionId) ?? null;

  const filteredSessions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return sessions;
    return sessions.filter((session) => {
      const title = session.title.toLowerCase();
      const sessionId = session.session_id.toLowerCase();
      return title.includes(needle) || sessionId.includes(needle);
    });
  }, [query, sessions]);

  const archivedMessages = useMemo(
    () => (history ? mapHistoryMessages(history) : []),
    [history],
  );
  const liveSessionReady =
    scope === "active" &&
    currentAgentId === agentId &&
    sessionsScope === "active" &&
    currentSessionId === selectedSessionId;

  function navigateWithUpdates(
    updates: Record<string, string | undefined>,
    mode: "push" | "replace" = "replace",
  ) {
    const params = buildParams(searchParams, updates);
    const nextQuery = params.toString();
    const href = nextQuery ? `${pathname}?${nextQuery}` : pathname;
    if (mode === "push") {
      router.push(href, { scroll: false });
      return;
    }
    router.replace(href, { scroll: false });
  }

  useEffect(() => {
    let cancelled = false;

    async function loadAgents() {
      setAgentsLoading(true);
      try {
        const rows = await getAgents();
        if (cancelled) return;
        setAgents(rows);
      } catch (error) {
        if (cancelled) return;
        setListError(error instanceof Error ? error.message : "Failed to load agents");
      } finally {
        if (!cancelled) {
          setAgentsLoading(false);
        }
      }
    }

    void loadAgents();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (agentsLoading || agents.length === 0) return;
    if (!requestedAgentId) return;
    if (requestedAgentId === agentId) return;
    navigateWithUpdates({ agent: agentId });
  }, [agentId, agents, agentsLoading, requestedAgentId]);

  useEffect(() => {
    let cancelled = false;

    async function loadSessions() {
      setSessionsLoading(true);
      setListError("");
      try {
        const rows = await getSessions(scope, agentId);
        if (cancelled) return;
        setSessions(rows);
      } catch (error) {
        if (cancelled) return;
        setSessions([]);
        setListError(error instanceof Error ? error.message : "Failed to load sessions");
      } finally {
        if (!cancelled) {
          setSessionsLoading(false);
        }
      }
    }

    if (!agentId) return;
    void loadSessions();

    return () => {
      cancelled = true;
    };
  }, [agentId, scope]);

  useEffect(() => {
    let cancelled = false;

    async function loadArchivedHistory() {
      if (scope !== "archived" || !selectedSessionId) {
        setHistory(null);
        if (scope === "active") {
          setDetailError("");
        }
        return;
      }

      setDetailLoading(true);
      setDetailError("");
      try {
        const nextHistory = await getSessionHistory(selectedSessionId, true, agentId);
        if (cancelled) return;
        setHistory(nextHistory);
      } catch (error) {
        if (cancelled) return;
        setHistory(null);
        setDetailError(
          error instanceof Error ? error.message : "Failed to load transcript",
        );
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }

    if (!agentId) return;
    void loadArchivedHistory();

    return () => {
      cancelled = true;
    };
  }, [agentId, scope, selectedSessionId]);

  useEffect(() => {
    let cancelled = false;

    async function syncLiveSession() {
      if (scope !== "active" || !selectedSessionId || !agentId) {
        setActiveSyncing(false);
        return;
      }

      if (
        currentAgentId === agentId &&
        sessionsScope === "active" &&
        currentSessionId === selectedSessionId
      ) {
        setActiveSyncing(false);
        setDetailError("");
        return;
      }

      setActiveSyncing(true);
      setDetailError("");
      try {
        if (currentAgentId !== agentId) {
          await setCurrentAgent(agentId);
        } else if (sessionsScope !== "active") {
          await setSessionsScope("active");
        }
        if (cancelled) return;
        await selectSession(selectedSessionId);
        if (cancelled) return;
        setDetailError("");
      } catch (error) {
        if (cancelled) return;
        setDetailError(
          error instanceof Error ? error.message : "Failed to activate session",
        );
      } finally {
        if (!cancelled) {
          setActiveSyncing(false);
        }
      }
    }

    void syncLiveSession();

    return () => {
      cancelled = true;
    };
  }, [
    agentId,
    currentAgentId,
    currentSessionId,
    scope,
    selectedSessionId,
    selectSession,
    sessionsScope,
    setCurrentAgent,
    setSessionsScope,
  ]);

  async function refreshCurrentSessions(nextScope = scope) {
    const rows = await getSessions(nextScope, agentId);
    setSessions(rows);
  }

  async function handleCreateSession() {
    setBusyAction("create");
    setStatus("");
    setListError("");
    try {
      const created = await createSession(undefined, agentId);
      await refreshCurrentSessions("active");
      setHistory(null);
      navigateWithUpdates(
        {
          agent: agentId,
          scope: "active",
          session: created.session_id,
        },
        "push",
      );
      setStatus("Created a new active session.");
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Failed to create session");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleArchiveSession() {
    if (!selectedSessionId) return;
    setBusyAction("archive");
    setStatus("");
    setListError("");
    try {
      await archiveSession(selectedSessionId, agentId);
      await refreshCurrentSessions("active");
      setHistory(null);
      navigateWithUpdates({ session: undefined });
      setStatus("Archived session.");
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Failed to archive session");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRestoreSession() {
    if (!selectedSessionId) return;
    setBusyAction("restore");
    setStatus("");
    setListError("");
    try {
      await restoreSession(selectedSessionId, agentId);
      await refreshCurrentSessions("archived");
      setHistory(null);
      navigateWithUpdates({ session: undefined });
      setStatus("Restored session to the active inbox.");
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Failed to restore session");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDeleteSession() {
    if (!selectedSessionId) return;
    setBusyAction("delete");
    setStatus("");
    setListError("");
    try {
      await deleteSession(selectedSessionId, scope === "archived", agentId);
      await refreshCurrentSessions(scope);
      setHistory(null);
      navigateWithUpdates({ session: undefined });
      setStatus("Deleted session.");
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Failed to delete session");
    } finally {
      setBusyAction(null);
    }
  }

  const detailContent =
    scope === "active" ? (
      <LiveConversation
        messages={liveSessionReady ? liveMessages : []}
        loading={activeSyncing}
        error={detailError || liveError || ""}
        isStreaming={liveSessionReady ? isStreaming : false}
        maxStepsPrompt={liveSessionReady ? maxStepsPrompt : null}
        onContinue={() => {
          void continueAfterMaxSteps();
        }}
        onCancel={() => {
          void cancelAfterMaxSteps();
        }}
      />
    ) : (
      <TranscriptFeed
        messages={archivedMessages}
        loading={detailLoading}
        error={detailError}
        emptyTitle="Archived Session"
        emptyDescription="This session is read-only in the operator console."
      />
    );
  const detailMessages =
    scope === "active"
      ? liveSessionReady
        ? liveMessages
        : []
      : archivedMessages;

  return (
    <main id="main-content" className="flex min-h-0 flex-1 flex-col p-3">
      <section className="grid min-h-0 flex-1 gap-3 md:grid-cols-[minmax(260px,340px)_minmax(0,1fr)] xl:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
        <section className="panel-shell flex min-h-0 flex-col">
          <div className="ui-panel-header">
            <div>
              <h1 className="ui-panel-title">Sessions</h1>
              <p className="mt-1 text-sm text-[var(--muted)]">
                Active chat home for operator conversations and archived transcript review.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone="neutral">
                {filteredSessions.length}/{sessions.length}
              </Badge>
              <Button
                type="button"
                size="sm"
                loading={busyAction === "create"}
                onClick={handleCreateSession}
              >
                New Session
              </Button>
            </div>
          </div>

          <div className="ui-scroll-area flex min-h-0 flex-1 flex-col gap-4 p-4">
            <div className="grid gap-3">
              <label className="grid gap-1">
                <span className="ui-label">Agent</span>
                <Select
                  aria-label="Filter sessions by agent"
                  className="ui-mono text-xs"
                  value={agentId}
                  onChange={(event) =>
                    navigateWithUpdates({
                      agent: event.target.value,
                      session: undefined,
                    })
                  }
                >
                  {(agentsLoading ? [] : agents).map((agent) => (
                    <option key={agent.agent_id} value={agent.agent_id}>
                      {agent.agent_id} ({agent.active_sessions}/{agent.archived_sessions})
                    </option>
                  ))}
                </Select>
              </label>

              <TabsList
                className="grid grid-cols-2"
                ariaLabel="Session scope"
                value={scope}
                onChange={(value) =>
                  navigateWithUpdates({
                    scope: normalizeScope(value),
                    session: undefined,
                  })
                }
              >
                <TabButton id="sessions-scope-active" value="active">
                  Active
                </TabButton>
                <TabButton id="sessions-scope-archived" value="archived">
                  Archived
                </TabButton>
              </TabsList>

              <label className="grid gap-1">
                <span className="ui-label">Search</span>
                <Input
                  aria-label="Search"
                  value={query}
                  onChange={(event) =>
                    navigateWithUpdates({ q: event.target.value || undefined })
                  }
                  placeholder="Search title or session id"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
            </div>

            {status ? (
              <p className="ui-helper" aria-live="polite">
                {status}
              </p>
            ) : null}
            {listError ? (
              <div className="ui-alert" role="alert">
                {listError}
              </div>
            ) : null}

            {sessionsLoading || agentsLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : filteredSessions.length === 0 ? (
              <EmptyState
                title={query ? "No matching sessions" : "No sessions"}
                description={
                  query
                    ? "Try a different title or session id search."
                    : scope === "archived"
                      ? "Archived sessions will appear here once conversations are stored."
                      : "Create a new session to start the inbox."
                }
              />
            ) : (
              <ul className="space-y-2">
                {filteredSessions.map((session) => {
                  const selected = session.session_id === selectedSessionId;
                  return (
                    <li key={session.session_id}>
                      <button
                        type="button"
                        className={`w-full rounded-md border p-3 text-left transition-colors duration-150 ${
                          selected
                            ? "border-[var(--accent-strong)] bg-[var(--accent-soft)]"
                            : "border-[var(--border)] bg-[var(--surface-3)] hover:border-[var(--border-strong)]"
                        }`}
                        onClick={() =>
                          navigateWithUpdates({ session: session.session_id }, "push")
                        }
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold text-[var(--text)]">
                              {session.title || "New Session"}
                            </div>
                            <div className="ui-mono mt-1 truncate text-xs text-[var(--muted)]">
                              {session.session_id}
                            </div>
                          </div>
                          <Badge tone={sessionScopeTone(scope)}>
                            {scope === "archived" ? "Archived" : "Live"}
                          </Badge>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--muted)]">
                          <span>Updated {formatTimestamp(session.updated_at)}</span>
                          <span>Created {formatTimestamp(session.created_at)}</span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        <section className="panel-shell hidden min-h-0 flex-col md:flex">
          <SessionDetailShell
            agentId={agentId}
            scope={scope}
            session={selectedSession}
            history={history}
            messages={detailMessages}
            busyAction={busyAction}
            status={status}
            onArchive={handleArchiveSession}
            onRestore={handleRestoreSession}
            onDelete={handleDeleteSession}
          >
            {detailContent}
          </SessionDetailShell>
        </section>
      </section>

      {selectedSession ? (
        <aside className="panel-shell fixed inset-3 z-50 flex min-h-0 flex-col md:hidden">
          <SessionDetailShell
            agentId={agentId}
            scope={scope}
            session={selectedSession}
            history={history}
            messages={detailMessages}
            busyAction={busyAction}
            status={status}
            onArchive={handleArchiveSession}
            onRestore={handleRestoreSession}
            onDelete={handleDeleteSession}
            onClose={() => navigateWithUpdates({ session: undefined })}
          >
            {detailContent}
          </SessionDetailShell>
        </aside>
      ) : null}
    </main>
  );
}

export default function SessionsPage() {
  return (
    <Suspense fallback={<SessionsPageFallback />}>
      <SessionsPageContent />
    </Suspense>
  );
}
