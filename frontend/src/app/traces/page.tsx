"use client";

import Link from "next/link";
import {
  type ReadonlyURLSearchParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import {
  AgentMeta,
  getAgents,
  getTraceEvent,
  listTraceEvents,
  TraceEventRecord,
  TraceEventsResponse,
} from "@/lib/api";
import {
  formatTraceTimestamp,
  normalizeTraceEventFilter,
  normalizeTraceTriggerFilter,
  normalizeTraceWindow,
  traceSummaryEntries,
  TraceEventFilter,
  TraceTriggerFilter,
  TraceWindow,
} from "@/lib/traces";
import { useAppStore } from "@/lib/store";
import {
  Badge,
  Button,
  EmptyState,
  Input,
  Select,
  Skeleton,
} from "@/components/ui/primitives";

const TRACE_WINDOW_OPTIONS: Array<{ label: string; value: TraceWindow }> = [
  { label: "1h", value: "1h" },
  { label: "4h", value: "4h" },
  { label: "12h", value: "12h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

const TRACE_EVENT_OPTIONS: Array<{ label: string; value: TraceEventFilter }> = [
  { label: "All events", value: "all" },
  { label: "Tool start", value: "tool_start" },
  { label: "Tool end", value: "tool_end" },
  { label: "LLM start", value: "llm_start" },
  { label: "LLM end", value: "llm_end" },
  { label: "LLM error", value: "llm_error" },
  { label: "Error", value: "error" },
  { label: "Unknown", value: "unknown" },
];

const TRACE_TRIGGER_OPTIONS: Array<{ label: string; value: TraceTriggerFilter }> = [
  { label: "All triggers", value: "all" },
  { label: "Chat", value: "chat" },
  { label: "Cron", value: "cron" },
  { label: "Heartbeat", value: "heartbeat" },
  { label: "Unknown", value: "unknown" },
];

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

type TraceDetailProps = {
  event: TraceEventRecord | null;
  loading: boolean;
  error: string;
  agentId: string;
  onClose?: () => void;
};

function TraceDetail({ event, loading, error, agentId, onClose }: TraceDetailProps) {
  if (loading) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-36 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-6">
        <div className="ui-alert" role="alert">
          {error}
        </div>
      </div>
    );
  }

  if (!event) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-6">
        <EmptyState
          title="Select a trace event"
          description="Choose an event from the timeline to inspect identifiers, payloads, and links back to runs or sessions."
        />
      </div>
    );
  }

  return (
    <>
      <div className="ui-panel-header">
        <div>
          <h2 className="ui-panel-title">Trace Detail</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
            <Badge tone="accent">{event.event}</Badge>
            <Badge tone="neutral">{event.source}</Badge>
            <Badge tone="neutral">{event.trigger_type}</Badge>
          </div>
        </div>
        {onClose ? (
          <Button type="button" size="sm" onClick={onClose}>
            Close
          </Button>
        ) : null}
      </div>

      <div className="ui-scroll-area flex min-h-0 flex-1 flex-col gap-3 p-4 text-sm">
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
          <div className="ui-label">Summary</div>
          <div className="mt-1 text-[var(--text)]">{event.summary || "—"}</div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
            <div className="ui-label">Timestamp</div>
            <div className="mt-1 text-[var(--text)]">
              {formatTraceTimestamp(event.timestamp_ms)}
            </div>
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
            <div className="ui-label">Event ID</div>
            <div className="ui-mono mt-1 break-all">{event.event_id}</div>
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
            <div className="ui-label">Run ID</div>
            <div className="ui-mono mt-1 break-all">{event.run_id || "—"}</div>
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
            <div className="ui-label">Session ID</div>
            <div className="ui-mono mt-1 break-all">{event.session_id || "—"}</div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {event.run_id ? (
            <Link
              href={`/runs?agent=${encodeURIComponent(agentId)}&run=${encodeURIComponent(event.run_id)}`}
              className="ui-btn ui-btn-sm"
            >
              Open Run
            </Link>
          ) : null}
          {event.session_id ? (
            <Link
              href={`/sessions?agent=${encodeURIComponent(agentId)}&session=${encodeURIComponent(event.session_id)}`}
              className="ui-btn ui-btn-sm"
            >
              Open Session
            </Link>
          ) : null}
        </div>

        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
          <div className="ui-label">Raw JSON</div>
          <pre className="ui-mono mt-2 whitespace-pre-wrap text-xs text-[var(--text)]">
            {JSON.stringify(event.details, null, 2)}
          </pre>
        </div>
      </div>
    </>
  );
}

function TracesPageFallback() {
  return (
    <main id="main-content" className="flex min-h-0 flex-1 flex-col p-3">
      <section className="panel-shell flex min-h-0 flex-1 flex-col">
        <div className="ui-panel-header">
          <div>
            <h1 className="ui-panel-title">Trace Explorer</h1>
            <p className="mt-1 text-sm text-[var(--muted)]">
              Loading persisted trace events...
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

function TracesPageContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { currentAgentId } = useAppStore();
  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [eventsResponse, setEventsResponse] = useState<TraceEventsResponse | null>(null);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState("");
  const [detail, setDetail] = useState<TraceEventRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const requestedAgentId = (searchParams.get("agent") ?? "").trim();
  const selectedWindow = normalizeTraceWindow(searchParams.get("window"));
  const selectedEvent = normalizeTraceEventFilter(searchParams.get("event"));
  const selectedTrigger = normalizeTraceTriggerFilter(searchParams.get("trigger"));
  const selectedRunId = (searchParams.get("run") ?? "").trim();
  const selectedSessionId = (searchParams.get("session") ?? "").trim();
  const selectedQuery = searchParams.get("q") ?? "";
  const selectedTraceId = (searchParams.get("trace") ?? "").trim();
  const fallbackAgentId = currentAgentId || agents[0]?.agent_id || "default";
  const agentId =
    agents.length > 0 && requestedAgentId
      ? agents.some((agent) => agent.agent_id === requestedAgentId)
        ? requestedAgentId
        : fallbackAgentId
      : requestedAgentId || fallbackAgentId;

  const events = eventsResponse?.events ?? [];
  const summaryEntries = useMemo(
    () => traceSummaryEntries(eventsResponse?.summary.by_event ?? {}),
    [eventsResponse],
  );

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
        setEventsError(error instanceof Error ? error.message : "Failed to load agents");
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

    async function loadEvents() {
      setEventsLoading(true);
      setEventsError("");
      try {
        const payload = await listTraceEvents({
          agentId,
          window: selectedWindow,
          event: selectedEvent,
          trigger: selectedTrigger,
          runId: selectedRunId,
          sessionId: selectedSessionId,
          query: selectedQuery,
          limit: 200,
        });
        if (cancelled) return;
        setEventsResponse(payload);
      } catch (error) {
        if (cancelled) return;
        setEventsResponse(null);
        setEventsError(
          error instanceof Error ? error.message : "Failed to load trace events",
        );
      } finally {
        if (!cancelled) {
          setEventsLoading(false);
        }
      }
    }

    if (!agentId) return;
    void loadEvents();

    return () => {
      cancelled = true;
    };
  }, [
    agentId,
    selectedEvent,
    selectedQuery,
    selectedRunId,
    selectedSessionId,
    selectedTrigger,
    selectedWindow,
  ]);

  useEffect(() => {
    let cancelled = false;

    async function loadDetail() {
      if (!selectedTraceId) {
        setDetail(null);
        setDetailError("");
        return;
      }

      setDetailLoading(true);
      setDetailError("");
      try {
        const payload = await getTraceEvent(selectedTraceId, agentId);
        if (cancelled) return;
        setDetail(payload);
      } catch (error) {
        if (cancelled) return;
        setDetail(null);
        setDetailError(
          error instanceof Error ? error.message : "Failed to load trace detail",
        );
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }

    if (!agentId) return;
    void loadDetail();

    return () => {
      cancelled = true;
    };
  }, [agentId, selectedTraceId]);

  return (
    <main
      id="main-content"
      data-testid="trace-page-main"
      className="app-main flex min-h-0 flex-1 flex-col overflow-hidden p-3"
    >
      <section
        data-testid="trace-layout-grid"
        className="grid min-h-0 flex-1 gap-3 overflow-hidden md:grid-cols-[minmax(0,1fr)_minmax(360px,460px)]"
      >
        <section className="panel-shell flex min-h-0 flex-col overflow-hidden">
          <div className="ui-panel-header">
            <div>
              <h1 className="ui-panel-title">Trace Explorer</h1>
              <p className="mt-1 text-sm text-[var(--muted)]">
                Persisted event timeline across audit steps and scheduler run events.
              </p>
            </div>
            <Badge tone="neutral">{eventsResponse?.total ?? 0} events</Badge>
          </div>

          <div
            data-testid="trace-timeline-scroll"
            className="ui-scroll-area flex min-h-0 flex-1 flex-col gap-4 p-4"
          >
            <div className="grid gap-3 md:grid-cols-4">
              <label className="grid gap-1">
                <span className="ui-label">Agent</span>
                <Select
                  aria-label="Filter traces by agent"
                  className="ui-mono text-xs"
                  value={agentId}
                  onChange={(event) =>
                    navigateWithUpdates({
                      agent: event.target.value,
                      trace: undefined,
                    })
                  }
                >
                  {(agentsLoading ? [] : agents).map((agent) => (
                    <option key={agent.agent_id} value={agent.agent_id}>
                      {agent.agent_id}
                    </option>
                  ))}
                </Select>
              </label>

              <label className="grid gap-1">
                <span className="ui-label">Window</span>
                <Select
                  aria-label="Filter traces by time window"
                  value={selectedWindow}
                  onChange={(event) =>
                    navigateWithUpdates({
                      window: normalizeTraceWindow(event.target.value),
                      trace: undefined,
                    })
                  }
                >
                  {TRACE_WINDOW_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </label>

              <label className="grid gap-1">
                <span className="ui-label">Event</span>
                <Select
                  aria-label="Filter traces by event type"
                  value={selectedEvent}
                  onChange={(event) =>
                    navigateWithUpdates({
                      event: normalizeTraceEventFilter(event.target.value),
                      trace: undefined,
                    })
                  }
                >
                  {TRACE_EVENT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </label>

              <label className="grid gap-1">
                <span className="ui-label">Trigger</span>
                <Select
                  aria-label="Filter traces by trigger"
                  value={selectedTrigger}
                  onChange={(event) =>
                    navigateWithUpdates({
                      trigger: normalizeTraceTriggerFilter(event.target.value),
                      trace: undefined,
                    })
                  }
                >
                  {TRACE_TRIGGER_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </label>

              <label className="grid gap-1 md:col-span-2">
                <span className="ui-label">Run ID</span>
                <Input
                  aria-label="Filter traces by run id"
                  value={selectedRunId}
                  onChange={(event) =>
                    navigateWithUpdates({
                      run: event.target.value || undefined,
                      trace: undefined,
                    })
                  }
                  placeholder="Optional run id"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>

              <label className="grid gap-1 md:col-span-2">
                <span className="ui-label">Session ID</span>
                <Input
                  aria-label="Filter traces by session id"
                  value={selectedSessionId}
                  onChange={(event) =>
                    navigateWithUpdates({
                      session: event.target.value || undefined,
                      trace: undefined,
                    })
                  }
                  placeholder="Optional session id"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>

              <label className="grid gap-1 md:col-span-4">
                <span className="ui-label">Search</span>
                <Input
                  aria-label="Search traces"
                  value={selectedQuery}
                  onChange={(event) =>
                    navigateWithUpdates({
                      q: event.target.value || undefined,
                      trace: undefined,
                    })
                  }
                  placeholder="Search summaries and payloads"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
            </div>

            {eventsResponse ? (
              <div className="grid gap-3 md:grid-cols-[160px_repeat(auto-fit,minmax(120px,1fr))]">
                <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                  <div className="ui-label">Matches</div>
                  <div className="mt-1 text-2xl font-semibold text-[var(--text)]">
                    {eventsResponse.summary.total_matches}
                  </div>
                </div>
                {summaryEntries.map(([eventName, count]) => (
                  <div
                    key={eventName}
                    className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3"
                  >
                    <div className="ui-label">{eventName}</div>
                    <div className="mt-1 text-xl font-semibold text-[var(--text)]">
                      {count}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            {eventsError ? (
              <div className="ui-alert" role="alert">
                {eventsError}
              </div>
            ) : null}

            {eventsLoading || agentsLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : events.length === 0 ? (
              <EmptyState
                title="No trace events"
                description="No persisted events matched the selected filters."
              />
            ) : (
              <ul className="space-y-2">
                {events.map((event) => {
                  const selected = event.event_id === selectedTraceId;
                  return (
                    <li key={event.event_id}>
                      <button
                        type="button"
                        className={`w-full rounded-md border p-3 text-left transition-colors duration-150 ${
                          selected
                            ? "border-[var(--accent-strong)] bg-[var(--accent-soft)]"
                            : "border-[var(--border)] bg-[var(--surface-3)] hover:border-[var(--border-strong)]"
                        }`}
                        onClick={() =>
                          navigateWithUpdates({ trace: event.event_id }, "push")
                        }
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="ui-mono truncate text-sm font-semibold text-[var(--text)]">
                              {event.event_id}
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                              <Badge tone="accent">{event.event}</Badge>
                              <Badge tone="neutral">{event.trigger_type}</Badge>
                              <Badge tone="neutral">{event.source}</Badge>
                            </div>
                          </div>
                          <div className="text-xs text-[var(--muted)]">
                            {formatTraceTimestamp(event.timestamp_ms)}
                          </div>
                        </div>

                        <div className="mt-3 text-sm text-[var(--text)]">
                          {event.summary || "—"}
                        </div>

                        <div className="mt-3 grid gap-2 text-xs text-[var(--muted)] md:grid-cols-2">
                          <div className="ui-mono">run {event.run_id || "—"}</div>
                          <div className="ui-mono">session {event.session_id || "—"}</div>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        <section
          data-testid="trace-detail-host"
          className="panel-shell hidden min-h-0 flex-col overflow-hidden md:flex md:h-full"
        >
          <TraceDetail
            event={detail}
            loading={detailLoading}
            error={detailError}
            agentId={agentId}
          />
        </section>
      </section>

      {selectedTraceId ? (
        <aside className="panel-shell fixed inset-3 z-50 flex min-h-0 flex-col md:hidden">
          <TraceDetail
            event={detail}
            loading={detailLoading}
            error={detailError}
            agentId={agentId}
            onClose={() => navigateWithUpdates({ trace: undefined })}
          />
        </aside>
      ) : null}
    </main>
  );
}

export default function TracesPage() {
  return (
    <Suspense fallback={<TracesPageFallback />}>
      <TracesPageContent />
    </Suspense>
  );
}
