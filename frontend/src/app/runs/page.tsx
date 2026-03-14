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
  Badge,
  Button,
  DataTable,
  EmptyState,
  Select,
  Skeleton,
  TableWrap,
} from "@/components/ui/primitives";
import {
  FilterBar,
  FilterGrid,
  MetricCard,
  MetricGrid,
  PageHeader,
  PageLayout,
  PageStack,
  SectionCard,
} from "@/components/ui/page-shell";
import {
  AgentMeta,
  getAgents,
  getUsageRecords,
  listCronFailures,
  listCronRuns,
  listHeartbeatRuns,
} from "@/lib/api";
import {
  buildRunLedgerRows,
  filterRunLedgerRows,
  formatRunMetric,
  getRunWindowStart,
  normalizeRunTriggerFilter,
  normalizeRunWindow,
  RunLedgerRow,
  RunTriggerFilter,
  RunWindow,
  windowToHours,
} from "@/lib/runs";
import { useAppStore } from "@/lib/store";

const RUN_WINDOW_OPTIONS: Array<{ label: string; value: RunWindow }> = [
  { label: "1h", value: "1h" },
  { label: "4h", value: "4h" },
  { label: "12h", value: "12h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 6,
  maximumFractionDigits: 6,
});

const integerFormatter = new Intl.NumberFormat("en-US");

function formatTimestamp(timestampMs: number): string {
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) return "—";
  return dateFormatter.format(new Date(timestampMs));
}

function formatCurrency(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return currencyFormatter.format(value);
}

function formatInteger(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return integerFormatter.format(value);
}

function formatDuration(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}ms`;
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

function statusTone(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "error") return "danger" as const;
  if (normalized.startsWith("skipped")) return "warn" as const;
  if (normalized === "recorded") return "accent" as const;
  if (normalized === "ok") return "success" as const;
  return "neutral" as const;
}

function sourceTone(source: RunLedgerRow["source"]) {
  if (source === "usage") return "neutral" as const;
  if (source === "cron") return "warn" as const;
  if (source === "heartbeat") return "accent" as const;
  return "neutral" as const;
}

function formatRunSourceLabel(source: RunLedgerRow["source"]) {
  if (source === "usage") return "Chat Usage";
  if (source === "cron") return "Cron Run";
  if (source === "heartbeat") return "Heartbeat Run";
  return source;
}

function describeRunSource(row: RunLedgerRow) {
  if (row.source === "usage") {
    return "This row comes from persisted chat token and cost accounting. It is recorded activity, not a scheduler status stream.";
  }
  if (row.source === "cron") {
    return "This row comes from the scheduler's cron run history.";
  }
  if (row.source === "heartbeat") {
    return "This row comes from the scheduler's heartbeat run history.";
  }
  return "This row came from a normalized operational source.";
}

function displayRunIdentifier(row: RunLedgerRow): string {
  return row.runId ?? row.jobId ?? row.label;
}

type RunDetailProps = {
  row: RunLedgerRow | null;
  agentId: string;
  onClose: () => void;
};

function RunDetailDrawer({ row, agentId, onClose }: RunDetailProps) {
  if (!row) return null;

  return (
    <aside className="ui-drawer panel-shell md:inset-y-3 md:right-3 md:left-auto md:w-[min(560px,92vw)]">
      <div className="flex h-full min-h-0 flex-col">
        <div className="ui-panel-header">
          <div>
            <h2 className="ui-panel-title">Run Detail</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
              <Badge tone={statusTone(row.status)}>{row.status}</Badge>
              <Badge tone={sourceTone(row.source)}>{formatRunSourceLabel(row.source)}</Badge>
            </div>
          </div>
          <Button type="button" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        <div className="ui-scroll-area flex min-h-0 flex-1 flex-col gap-3 p-4 text-sm">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Time</div>
              <div className="mt-1 text-[var(--text)]">
                {formatTimestamp(row.timestampMs)}
              </div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Trigger</div>
              <div className="mt-1 text-[var(--text)]">{row.triggerType}</div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Origin</div>
              <div className="mt-1 text-[var(--text)]">
                {describeRunSource(row)}
              </div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Primary Identifier</div>
              <div className="ui-mono mt-1 break-all">{displayRunIdentifier(row)}</div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Duration</div>
              <div className="mt-1 text-[var(--text)]">
                {formatDuration(row.durationMs)}
              </div>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Run ID</div>
              <div className="ui-mono mt-1 break-all">
                {formatRunMetric(row.runId)}
              </div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Session ID</div>
              <div className="ui-mono mt-1 break-all">
                {formatRunMetric(row.sessionId)}
              </div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Job ID</div>
              <div className="ui-mono mt-1 break-all">
                {formatRunMetric(row.jobId)}
              </div>
            </div>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Tokens / Cost</div>
              <div className="mt-1 text-[var(--text)]">
                {formatInteger(row.totalTokens)} / {formatCurrency(row.costUsd)}
              </div>
            </div>
          </div>

          {row.errorSummary ? (
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
              <div className="ui-label">Info</div>
              <div className="mt-1 whitespace-pre-wrap text-[var(--text)]">
                {row.errorSummary}
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap gap-2">
            {row.sessionId ? (
              <Link
                href={`/sessions?agent=${encodeURIComponent(agentId)}&session=${encodeURIComponent(row.sessionId)}`}
                className="ui-btn ui-btn-sm"
              >
                Open Session
              </Link>
            ) : null}
            <Link
              href={`/traces?agent=${encodeURIComponent(agentId)}${row.runId ? `&run=${encodeURIComponent(row.runId)}` : ""}${row.sessionId ? `&session=${encodeURIComponent(row.sessionId)}` : ""}`}
              className="ui-btn ui-btn-sm ui-btn-ghost"
            >
              Open Traces
            </Link>
          </div>

          <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
            <div className="ui-label">Source Payload</div>
            <pre className="ui-mono mt-2 whitespace-pre-wrap text-xs text-[var(--text)]">
              {JSON.stringify(row.raw, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </aside>
  );
}

function RunsPageFallback() {
  return (
    <PageLayout>
      <PageStack>
        <PageHeader
          eyebrow="Unified ledger"
          title="Runs"
          description="Loading run ledger..."
        />
        <div className="panel-shell space-y-3 p-4">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      </PageStack>
    </PageLayout>
  );
}

function RunsPageContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { currentAgentId } = useAppStore();

  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [rows, setRows] = useState<RunLedgerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const requestedAgentId = (searchParams.get("agent") ?? "").trim();
  const selectedWindow = normalizeRunWindow(searchParams.get("window"));
  const selectedTrigger = normalizeRunTriggerFilter(searchParams.get("trigger"));
  const selectedRunId = (searchParams.get("run") ?? "").trim();
  const fallbackAgentId = currentAgentId || agents[0]?.agent_id || "default";
  const agentId =
    agents.length > 0 && requestedAgentId
      ? agents.some((agent) => agent.agent_id === requestedAgentId)
        ? requestedAgentId
        : fallbackAgentId
      : requestedAgentId || fallbackAgentId;

  const filteredRows = useMemo(
    () =>
      filterRunLedgerRows(rows, selectedTrigger, {
        minimumTimestampMs: getRunWindowStart(selectedWindow),
      }),
    [rows, selectedTrigger, selectedWindow],
  );
  const sourceCounts = useMemo(
    () =>
      filteredRows.reduce(
        (acc, row) => {
          acc[row.source] += 1;
          if (row.status.toLowerCase() === "error") {
            acc.errors += 1;
          }
          return acc;
        },
        { usage: 0, cron: 0, heartbeat: 0, errors: 0 },
      ),
    [filteredRows],
  );

  const selectedRow =
    filteredRows.find((row) => row.rowId === selectedRunId) ??
    rows.find((row) => row.rowId === selectedRunId) ??
    null;

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
      } catch (nextError) {
        if (cancelled) return;
        setError(
          nextError instanceof Error ? nextError.message : "Failed to load agents",
        );
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

    async function loadRuns() {
      setLoading(true);
      setError("");

      try {
        const windowHours = windowToHours(selectedWindow);
        const shouldLoadCron =
          selectedTrigger === "all" || selectedTrigger === "cron";
        const shouldLoadHeartbeat =
          selectedTrigger === "all" || selectedTrigger === "heartbeat";

        const [usageRecords, cronRuns, cronFailures, heartbeatRuns] =
          await Promise.all([
            getUsageRecords({
              sinceHours: windowHours,
              agentId,
              limit: 500,
            }),
            shouldLoadCron ? listCronRuns(agentId, 200) : Promise.resolve([]),
            shouldLoadCron
              ? listCronFailures(agentId, 200)
              : Promise.resolve([]),
            shouldLoadHeartbeat
              ? listHeartbeatRuns(agentId, 200)
              : Promise.resolve([]),
          ]);

        if (cancelled) return;
        setRows(
          buildRunLedgerRows({
            usageRecords,
            cronRuns,
            cronFailures,
            heartbeatRuns,
          }),
        );
      } catch (nextError) {
        if (cancelled) return;
        setRows([]);
        setError(
          nextError instanceof Error ? nextError.message : "Failed to load runs",
        );
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    if (!agentId) return;
    void loadRuns();

    return () => {
      cancelled = true;
    };
  }, [agentId, selectedTrigger, selectedWindow]);

  return (
    <PageLayout>
      <PageStack>
        <PageHeader
          eyebrow="Unified ledger"
          title="Runs"
          description="Cross-check chat usage, cron jobs, and heartbeat activity in a single operational timeline."
          meta={
            <>
              <Badge tone="neutral">{filteredRows.length} rows</Badge>
              <Badge tone="accent">Agent {agentId}</Badge>
              {sourceCounts.errors > 0 ? (
                <Badge tone="danger">{sourceCounts.errors} error rows</Badge>
              ) : null}
            </>
          }
        />

        <FilterBar>
          <FilterGrid className="md:grid-cols-3">
            <label className="grid gap-1">
              <span className="ui-label">Agent</span>
              <Select
                aria-label="Filter runs by agent"
                className="ui-mono text-xs"
                value={agentId}
                onChange={(event) =>
                  navigateWithUpdates({
                    agent: event.target.value,
                    run: undefined,
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
                aria-label="Filter runs by time window"
                value={selectedWindow}
                onChange={(event) =>
                  navigateWithUpdates({
                    window: normalizeRunWindow(event.target.value),
                    run: undefined,
                  })
                }
              >
                {RUN_WINDOW_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>

            <label className="grid gap-1">
              <span className="ui-label">Trigger</span>
              <Select
                aria-label="Filter runs by trigger"
                value={selectedTrigger}
                onChange={(event) =>
                  navigateWithUpdates({
                    trigger: normalizeRunTriggerFilter(event.target.value),
                    run: undefined,
                  })
                }
              >
                <option value="all">All triggers</option>
                <option value="chat">Chat</option>
                <option value="cron">Cron</option>
                <option value="heartbeat">Heartbeat</option>
                </Select>
              </label>
          </FilterGrid>
        </FilterBar>

        <MetricGrid>
          <MetricCard
            label="Visible rows"
            value={filteredRows.length}
            meta={`Window ${selectedWindow}`}
            tone="accent"
          />
          <MetricCard
            label="Chat usage"
            value={sourceCounts.usage}
            meta="Token accounting rows"
          />
          <MetricCard
            label="Scheduler runs"
            value={sourceCounts.cron + sourceCounts.heartbeat}
            meta={`Cron ${sourceCounts.cron} · Heartbeat ${sourceCounts.heartbeat}`}
            tone="signal"
          />
          <MetricCard
            label="Error rows"
            value={sourceCounts.errors}
            meta="Rows marked with operational errors"
            tone={sourceCounts.errors > 0 ? "danger" : "success"}
          />
        </MetricGrid>

        <SectionCard
          title="Run ledger"
          description="Select a row to inspect identifiers, payloads, and links back to sessions or traces."
          toolbar={<Badge tone="neutral">{selectedTrigger} trigger</Badge>}
          contentClassName="ui-scroll-area flex min-h-0 flex-1 flex-col gap-4"
        >

          {error ? (
            <div className="ui-alert" role="alert">
              {error}
            </div>
          ) : null}

          {loading || agentsLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : filteredRows.length === 0 ? (
            <EmptyState
              title="No Runs"
              description="No run records matched the selected agent, window, and trigger filters."
            />
          ) : (
            <>
              <div className="space-y-2 md:hidden">
                {filteredRows.map((row) => (
                  <article
                    key={row.rowId}
                    className={`rounded-md border p-3 text-sm ${
                      row.rowId === selectedRunId
                        ? "border-[var(--accent-strong)] bg-[var(--accent-soft)]"
                        : "border-[var(--border)] bg-[var(--surface-3)]"
                    }`}
                  >
                    <button
                      type="button"
                      className="w-full text-left"
                      onClick={() =>
                        navigateWithUpdates({ run: row.rowId }, "push")
                      }
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="ui-mono text-sm">
                          {displayRunIdentifier(row)}
                        </span>
                        <Badge tone={statusTone(row.status)}>{row.status}</Badge>
                      </div>
                      <div className="mt-2 text-xs text-[var(--muted)]">
                        {formatTimestamp(row.timestampMs)} · {row.triggerType}
                      </div>
                      <div className="mt-2 text-xs text-[var(--muted)]">
                        Tokens {formatInteger(row.totalTokens)} · Cost{" "}
                        {formatCurrency(row.costUsd)}
                      </div>
                    </button>
                  </article>
                ))}
              </div>

              <TableWrap className="hidden md:block">
                <DataTable>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Trigger</th>
                      <th>Status</th>
                      <th>Identifier</th>
                      <th>Target</th>
                      <th>Tokens</th>
                      <th>Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((row) => (
                      <tr
                        key={row.rowId}
                        tabIndex={0}
                        className={`cursor-pointer ${
                          row.rowId === selectedRunId
                            ? "bg-[var(--accent-soft)]"
                            : ""
                        }`}
                        onClick={() =>
                          navigateWithUpdates({ run: row.rowId }, "push")
                        }
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            navigateWithUpdates({ run: row.rowId }, "push");
                          }
                        }}
                      >
                        <td>{formatTimestamp(row.timestampMs)}</td>
                        <td>{row.triggerType}</td>
                        <td>
                          <Badge tone={statusTone(row.status)}>{row.status}</Badge>
                        </td>
                        <td className="ui-mono">{displayRunIdentifier(row)}</td>
                        <td className="ui-mono">
                          {row.sessionId ?? row.jobId ?? "—"}
                        </td>
                        <td>{formatInteger(row.totalTokens)}</td>
                        <td>{formatCurrency(row.costUsd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </TableWrap>
            </>
          )}
        </SectionCard>
      </PageStack>

      <RunDetailDrawer
        row={selectedRow}
        agentId={agentId}
        onClose={() => navigateWithUpdates({ run: undefined })}
      />
    </PageLayout>
  );
}

export default function RunsPage() {
  return (
    <Suspense fallback={<RunsPageFallback />}>
      <RunsPageContent />
    </Suspense>
  );
}
