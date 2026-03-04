"use client";

import { useEffect, useMemo, useState } from "react";

import { Navbar } from "@/components/layout/Navbar";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  Input,
  Select,
  Skeleton,
  TableWrap,
} from "@/components/ui/primitives";
import {
  createCronJob,
  CronJob,
  deleteCronJob,
  getAgents,
  getHeartbeatConfig,
  HeartbeatConfig,
  getSchedulerMetrics,
  getSchedulerMetricsTimeseries,
  listCronFailures,
  listCronJobs,
  listCronRuns,
  listHeartbeatRuns,
  runCronJob,
  SchedulerMetrics,
  SchedulerMetricsSeries,
  SchedulerMetricsWindow,
  updateCronJob,
  updateHeartbeatConfig,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type ScheduleType = "at" | "every" | "cron";

type JobDraft = {
  id: string | null;
  name: string;
  schedule_type: ScheduleType;
  schedule: string;
  prompt: string;
  enabled: boolean;
};

const EMPTY_DRAFT: JobDraft = {
  id: null,
  name: "",
  schedule_type: "every",
  schedule: "300",
  prompt: "",
  enabled: true,
};

const METRICS_WINDOWS: Array<{ label: string; value: SchedulerMetricsWindow }> = [
  { label: "1h", value: "1h" },
  { label: "4h", value: "4h" },
  { label: "12h", value: "12h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

function asDateTime(value: unknown): string {
  const ts = Number(value);
  if (!Number.isFinite(ts) || ts <= 0) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function asRunTime(value: unknown): string {
  const ts = Number(value);
  if (!Number.isFinite(ts) || ts <= 0) return "—";
  return new Date(ts).toLocaleString();
}

function asMs(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}ms`;
}

function timeseriesBucket(window: SchedulerMetricsWindow): "1m" | "5m" | "15m" | "1h" {
  if (window === "1h") return "1m";
  if (window === "4h" || window === "12h") return "5m";
  if (window === "24h") return "15m";
  return "1h";
}

export default function SchedulerPage() {
  const { currentAgentId } = useAppStore();
  const [agents, setAgents] = useState<string[]>(["default"]);
  const [agentId, setAgentId] = useState<string>(currentAgentId || "default");
  const [metricsWindow, setMetricsWindow] = useState<SchedulerMetricsWindow>("24h");
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);
  const [failures, setFailures] = useState<Array<Record<string, unknown>>>([]);
  const [heartbeatRuns, setHeartbeatRuns] = useState<
    Array<Record<string, unknown>>
  >([]);
  const [metrics, setMetrics] = useState<SchedulerMetrics | null>(null);
  const [metricsSeries, setMetricsSeries] = useState<SchedulerMetricsSeries | null>(
    null,
  );
  const [heartbeat, setHeartbeat] = useState<HeartbeatConfig>({
    enabled: false,
    interval_seconds: 300,
    timezone: "UTC",
    active_start_hour: 9,
    active_end_hour: 21,
    session_id: "__heartbeat__",
  });
  const [draft, setDraft] = useState<JobDraft>(EMPTY_DRAFT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [submitAttempted, setSubmitAttempted] = useState(false);

  async function refreshAll(nextAgentId: string, window: SchedulerMetricsWindow) {
    setLoading(true);
    setError("");
    try {
      const [
        jobRows,
        runRows,
        failureRows,
        heartbeatConfig,
        heartbeatRunRows,
        metricsSummary,
        metricsTrend,
      ] = await Promise.all([
        listCronJobs(nextAgentId),
        listCronRuns(nextAgentId, 100),
        listCronFailures(nextAgentId, 100),
        getHeartbeatConfig(nextAgentId),
        listHeartbeatRuns(nextAgentId, 100),
        getSchedulerMetrics(nextAgentId, window),
        getSchedulerMetricsTimeseries(nextAgentId, window, timeseriesBucket(window)),
      ]);
      setJobs(jobRows);
      setRuns(runRows);
      setFailures(failureRows);
      setHeartbeat(heartbeatConfig);
      setHeartbeatRuns(heartbeatRunRows);
      setMetrics(metricsSummary);
      setMetricsSeries(metricsTrend);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load scheduler data",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadAgents() {
      try {
        const rows = await getAgents();
        if (cancelled) return;
        const ids = rows.map((item) => item.agent_id);
        const safeIds = ids.length > 0 ? ids : ["default"];
        setAgents(safeIds);

        const preferred = [currentAgentId, agentId, "default", safeIds[0]];
        const selected =
          preferred.find(
            (candidate) => Boolean(candidate) && safeIds.includes(String(candidate)),
          ) ?? safeIds[0];
        setAgentId(selected);
      } catch {
        if (!cancelled) {
          setAgents(["default"]);
          setAgentId(currentAgentId || "default");
        }
      }
    }
    void loadAgents();
    return () => {
      cancelled = true;
    };
  }, [currentAgentId]);

  useEffect(() => {
    void refreshAll(agentId, metricsWindow);
  }, [agentId, metricsWindow]);

  const recentRuns = useMemo(() => runs.slice(0, 10), [runs]);
  const recentFailures = useMemo(() => failures.slice(0, 10), [failures]);
  const recentHeartbeat = useMemo(
    () => heartbeatRuns.slice(0, 10),
    [heartbeatRuns],
  );
  const trendPoints = useMemo(() => metricsSeries?.points ?? [], [metricsSeries]);
  const trendMax = useMemo(
    () => Math.max(1, ...trendPoints.map((point) => point.total)),
    [trendPoints],
  );

  async function handleSubmitJob() {
    setSubmitAttempted(true);
    if (!draft.prompt.trim() || !draft.schedule.trim()) {
      setError("Schedule and prompt are required.");
      return;
    }
    setError("");
    try {
      if (draft.id) {
        await updateCronJob(
          draft.id,
          {
            name: draft.name,
            schedule_type: draft.schedule_type,
            schedule: draft.schedule,
            prompt: draft.prompt,
            enabled: draft.enabled,
          },
          agentId,
        );
      } else {
        await createCronJob(
          {
            name: draft.name,
            schedule_type: draft.schedule_type,
            schedule: draft.schedule,
            prompt: draft.prompt,
            enabled: draft.enabled,
          },
          agentId,
        );
      }
      setDraft(EMPTY_DRAFT);
      setSubmitAttempted(false);
      await refreshAll(agentId, metricsWindow);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save cron job");
    }
  }

  return (
    <main
      id="main-content"
      className="flex min-h-dvh flex-col"
    >
      <Navbar />
      <section className="flex flex-1 min-h-0 min-w-0 flex-col gap-3 overflow-y-auto p-3 pb-5">
        <div className="panel-shell">
          <div className="ui-panel-header">
            <h1 className="ui-panel-title">Scheduler</h1>
            <div className="flex items-center gap-2">
              <Select
                aria-label="Scheduler agent switch"
                className="ui-mono min-h-[36px] w-[160px] text-sm"
                value={agentId}
                onChange={(event) => setAgentId(event.target.value)}
              >
                {agents.map((id) => (
                  <option key={`header-${id}`} value={id}>
                    {id}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Scheduler metrics window"
                className="min-h-[36px] w-[92px] text-sm"
                value={metricsWindow}
                onChange={(event) =>
                  setMetricsWindow(event.target.value as SchedulerMetricsWindow)
                }
              >
                {METRICS_WINDOWS.map((window) => (
                  <option key={`window-${window.value}`} value={window.value}>
                    {window.label}
                  </option>
                ))}
              </Select>
              {loading ? (
                <Badge tone="accent">Loading</Badge>
              ) : (
                <Badge tone="success">Ready</Badge>
              )}
              {error ? <Badge tone="danger">Error</Badge> : null}
              <Badge tone="neutral">Agent {agentId}</Badge>
            </div>
          </div>
          <div className="grid gap-3 p-4 md:grid-cols-5">
            <label className="min-w-0">
              <span className="ui-label">Agent</span>
              <Select
                className="mt-1 ui-mono text-sm"
                value={agentId}
                onChange={(event) => setAgentId(event.target.value)}
              >
                {agents.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </Select>
            </label>
            <label className="min-w-0">
              <span className="ui-label">Schedule Type</span>
              <Select
                className="mt-1 ui-mono text-sm"
                value={draft.schedule_type}
                onChange={(event) =>
                  setDraft((prev) => ({
                    ...prev,
                    schedule_type: event.target.value as ScheduleType,
                  }))
                }
              >
                <option value="every">every (seconds)</option>
                <option value="cron">cron (5 fields)</option>
                <option value="at">at (ISO datetime)</option>
              </Select>
            </label>
            <label className="min-w-0">
              <span className="ui-label">Schedule</span>
              <Input
                className="mt-1 ui-mono text-sm"
                invalid={submitAttempted && !draft.schedule.trim()}
                hintId="scheduler-schedule-hint"
                errorId="scheduler-schedule-error"
                value={draft.schedule}
                onChange={(event) =>
                  setDraft((prev) => ({
                    ...prev,
                    schedule: event.target.value,
                  }))
                }
                placeholder={
                  draft.schedule_type === "every"
                    ? "300"
                    : draft.schedule_type === "cron"
                      ? "*/5 * * * *"
                      : "2026-03-01T10:00:00Z"
                }
              />
              <span
                id={
                  submitAttempted && !draft.schedule.trim()
                    ? "scheduler-schedule-error"
                    : "scheduler-schedule-hint"
                }
                className="ui-helper mt-1 block"
              >
                {submitAttempted && !draft.schedule.trim()
                  ? "Schedule is required."
                  : "Use seconds, cron, or ISO datetime depending on schedule type."}
              </span>
            </label>
            <label className="min-w-0 md:col-span-2">
              <span className="ui-label">Prompt</span>
              <Input
                className="mt-1 text-sm"
                invalid={submitAttempted && !draft.prompt.trim()}
                hintId="scheduler-prompt-hint"
                errorId="scheduler-prompt-error"
                value={draft.prompt}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, prompt: event.target.value }))
                }
                placeholder="Prompt executed when this cron job runs"
              />
              <span
                id={
                  submitAttempted && !draft.prompt.trim()
                    ? "scheduler-prompt-error"
                    : "scheduler-prompt-hint"
                }
                className="ui-helper mt-1 block"
              >
                {submitAttempted && !draft.prompt.trim()
                  ? "Prompt is required."
                  : "This prompt is sent when the job executes."}
              </span>
            </label>
            <label className="min-w-0">
              <span className="ui-label">Name</span>
              <Input
                className="mt-1 text-sm"
                value={draft.name}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, name: event.target.value }))
                }
                placeholder="optional job name"
              />
            </label>
            <label className="flex items-center gap-2 pt-6 text-sm text-[var(--muted)]">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) =>
                  setDraft((prev) => ({
                    ...prev,
                    enabled: event.target.checked,
                  }))
                }
              />
              Enabled
            </label>
            <div className="flex items-end gap-2 md:col-span-3">
              <Button
                type="button"
                className="px-3 text-sm"
                onClick={() => void handleSubmitJob()}
              >
                {draft.id ? "Update Job" : "Create Job"}
              </Button>
              {draft.id ? (
                <Button
                  type="button"
                  className="px-3 text-sm"
                  onClick={() => {
                    setDraft(EMPTY_DRAFT);
                    setSubmitAttempted(false);
                  }}
                >
                  Cancel Edit
                </Button>
              ) : null}
            </div>
          </div>
          {error ? (
            <div className="px-4 pb-4">
              <div className="ui-alert" role="alert">
                {error}
              </div>
            </div>
          ) : null}
        </div>

        <div className="grid min-w-0 gap-3 lg:grid-cols-4">
          <div className="panel-shell p-4">
            <div className="ui-label">Scheduler Events</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {metrics?.totals.events ?? 0}
            </div>
            <div className="mt-1 text-xs text-[var(--muted)]">
              Cron {metrics?.totals.cron_events ?? 0} · Heartbeat{" "}
              {metrics?.totals.heartbeat_events ?? 0}
            </div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Cron Success Rate</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {metrics?.cron.success_rate ?? 0}%
            </div>
            <div className="mt-1 text-xs text-[var(--muted)]">
              ok {metrics?.cron.ok ?? 0} · error {metrics?.cron.error ?? 0}
            </div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Duration p90 / p99</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {asMs(metrics?.duration.p90_ms)} / {asMs(metrics?.duration.p99_ms)}
            </div>
            <div className="mt-1 text-xs text-[var(--muted)]">
              avg {asMs(metrics?.duration.avg_ms)} · max{" "}
              {asMs(metrics?.duration.max_ms)}
            </div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Latency p90 / p99</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {asMs(metrics?.latency.p90_ms)} / {asMs(metrics?.latency.p99_ms)}
            </div>
            <div className="mt-1 text-xs text-[var(--muted)]">
              avg {asMs(metrics?.latency.avg_ms)} · max{" "}
              {asMs(metrics?.latency.max_ms)}
            </div>
          </div>
        </div>

        <div className="panel-shell min-w-0">
          <div className="ui-panel-header">
            <h2 className="ui-panel-title">Observability Trend</h2>
            <Badge tone="neutral">
              {metricsSeries?.points.length ?? 0} buckets
            </Badge>
          </div>
          <div className="p-4">
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ) : trendPoints.length === 0 ? (
              <EmptyState
                title="No Trend Data"
                description="No scheduler events in the selected window."
              />
            ) : (
              <>
                <div className="h-28 w-full">
                  <svg
                    viewBox={`0 0 ${Math.max(1, trendPoints.length)} 100`}
                    preserveAspectRatio="none"
                    className="h-full w-full"
                  >
                    {trendPoints.map((point, index) => {
                      const height = (point.total / trendMax) * 92;
                      const y = 96 - height;
                      return (
                        <rect
                          key={`${point.ts_ms}-${index}`}
                          x={index + 0.12}
                          y={y}
                          width={0.76}
                          height={Math.max(2, height)}
                          rx={0.1}
                          fill="var(--accent)"
                          opacity={0.88}
                        />
                      );
                    })}
                  </svg>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
                  {trendPoints.slice(Math.max(0, trendPoints.length - 8)).map((point) => (
                    <span
                      key={`trend-label-${point.ts_ms}`}
                      className="rounded border border-[var(--border)] px-2 py-0.5"
                    >
                      {new Date(point.ts_ms).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                      : {point.total}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        <div className="grid min-w-0 gap-3 lg:grid-cols-3">
          <div className="panel-shell min-w-0 lg:col-span-2">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Cron Jobs</h2>
              <Badge tone="neutral">{jobs.length} jobs</Badge>
            </div>
            <div className="p-3">
              {loading ? (
                <div className="space-y-2">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : jobs.length === 0 ? (
                <EmptyState
                  title="No Cron Jobs"
                  description="Create a cron job to start scheduled automation."
                />
              ) : (
                <>
                  <div className="space-y-2 lg:hidden">
                    {jobs.map((job) => (
                      <article
                        key={`${job.id}-mobile`}
                        className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="ui-mono">{job.name || job.id.slice(0, 8)}</div>
                          <Badge tone={job.enabled ? "success" : "warn"}>
                            {job.enabled ? "Enabled" : "Disabled"}
                          </Badge>
                        </div>
                        <div className="ui-mono mt-1 text-xs text-[var(--muted)]">
                          {job.schedule_type} {job.schedule}
                        </div>
                        <div className="mt-2 text-xs text-[var(--muted)]">
                          Next run {asDateTime(job.next_run_ts)} · failures {job.failure_count}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-1">
                          <Button
                            type="button"
                            size="sm"
                            onClick={() =>
                              setDraft({
                                id: job.id,
                                name: job.name,
                                schedule_type: job.schedule_type,
                                schedule: job.schedule,
                                prompt: job.prompt,
                                enabled: job.enabled,
                              })
                            }
                          >
                            Edit
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            onClick={async () => {
                              await runCronJob(job.id, agentId);
                              await refreshAll(agentId, metricsWindow);
                            }}
                          >
                            Run now
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="danger"
                            onClick={async () => {
                              await deleteCronJob(job.id, agentId);
                              await refreshAll(agentId, metricsWindow);
                            }}
                          >
                            Delete
                          </Button>
                        </div>
                      </article>
                    ))}
                  </div>
                  <TableWrap className="hidden max-h-[430px] lg:block">
                    <DataTable>
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Schedule</th>
                          <th>Enabled</th>
                          <th>Next Run</th>
                          <th>Failure</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.map((job) => (
                          <tr key={job.id}>
                            <td className="ui-mono">
                              {job.name || job.id.slice(0, 8)}
                            </td>
                            <td className="ui-mono">
                              {job.schedule_type} {job.schedule}
                            </td>
                            <td>{job.enabled ? "yes" : "no"}</td>
                            <td>{asDateTime(job.next_run_ts)}</td>
                            <td>{job.failure_count}</td>
                            <td>
                              <div className="flex gap-1">
                                <Button
                                  type="button"
                                  size="sm"
                                  onClick={() =>
                                    setDraft({
                                      id: job.id,
                                      name: job.name,
                                      schedule_type: job.schedule_type,
                                      schedule: job.schedule,
                                      prompt: job.prompt,
                                      enabled: job.enabled,
                                    })
                                  }
                                >
                                  Edit
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  onClick={async () => {
                                    await runCronJob(job.id, agentId);
                                    await refreshAll(agentId, metricsWindow);
                                  }}
                                >
                                  Run now
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="danger"
                                  onClick={async () => {
                                    await deleteCronJob(job.id, agentId);
                                    await refreshAll(agentId, metricsWindow);
                                  }}
                                >
                                  Delete
                                </Button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </TableWrap>
                </>
              )}
            </div>
          </div>

          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Heartbeat</h2>
              <Badge tone={heartbeat.enabled ? "success" : "warn"}>
                {heartbeat.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            <div className="space-y-2 p-4">
              <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
                <input
                  type="checkbox"
                  checked={heartbeat.enabled}
                  onChange={(event) =>
                    setHeartbeat((prev) => ({
                      ...prev,
                      enabled: event.target.checked,
                    }))
                  }
                />
                Enabled
              </label>
              <label className="block">
                <span className="ui-label">Interval Seconds</span>
                <Input
                  className="mt-1 ui-mono text-sm"
                  value={String(heartbeat.interval_seconds)}
                  onChange={(event) =>
                    setHeartbeat((prev) => ({
                      ...prev,
                      interval_seconds: Number(event.target.value || 0),
                    }))
                  }
                />
              </label>
              <label className="block">
                <span className="ui-label">Timezone</span>
                <Input
                  className="mt-1 ui-mono text-sm"
                  value={heartbeat.timezone}
                  onChange={(event) =>
                    setHeartbeat((prev) => ({
                      ...prev,
                      timezone: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="block">
                <span className="ui-label">Active Start Hour</span>
                <Input
                  className="mt-1 ui-mono text-sm"
                  value={String(heartbeat.active_start_hour)}
                  onChange={(event) =>
                    setHeartbeat((prev) => ({
                      ...prev,
                      active_start_hour: Number(event.target.value || 0),
                    }))
                  }
                />
              </label>
              <label className="block">
                <span className="ui-label">Active End Hour</span>
                <Input
                  className="mt-1 ui-mono text-sm"
                  value={String(heartbeat.active_end_hour)}
                  onChange={(event) =>
                    setHeartbeat((prev) => ({
                      ...prev,
                      active_end_hour: Number(event.target.value || 0),
                    }))
                  }
                />
              </label>
              <label className="block">
                <span className="ui-label">Session ID</span>
                <Input
                  className="mt-1 ui-mono text-sm"
                  value={heartbeat.session_id}
                  onChange={(event) =>
                    setHeartbeat((prev) => ({
                      ...prev,
                      session_id: event.target.value,
                    }))
                  }
                />
              </label>
              <Button
                type="button"
                className="w-full text-sm"
                loading={loading}
                onClick={async () => {
                  await updateHeartbeatConfig(heartbeat, agentId);
                  await refreshAll(agentId, metricsWindow);
                }}
              >
                Save Heartbeat
              </Button>
            </div>
          </div>
        </div>

        <div className="grid min-w-0 gap-3 lg:grid-cols-3">
          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Recent Runs</h2>
              <Badge tone="neutral">{recentRuns.length}</Badge>
            </div>
            <div className="p-3">
              {loading ? (
                <div className="space-y-2">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ) : recentRuns.length === 0 ? (
                <EmptyState
                  title="No Runs"
                  description="No recent run records."
                />
              ) : (
                <>
                  <div className="space-y-2 md:hidden">
                    {recentRuns.map((row, idx) => (
                      <article
                        key={`${idx}-runs-mobile`}
                        className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm"
                      >
                        <div className="ui-mono text-sm">
                          {String(row.name ?? row.job_id ?? "unknown")}
                        </div>
                        <div className="mt-1 text-xs text-[var(--muted)]">
                          {asRunTime(row.timestamp_ms)}
                        </div>
                        <div className="mt-2 text-xs text-[var(--muted)]">
                          Status {String(row.status ?? "ok")}
                        </div>
                      </article>
                    ))}
                  </div>
                  <TableWrap className="hidden max-h-[320px] md:block">
                    <DataTable>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Job</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentRuns.map((row, idx) => (
                          <tr key={idx}>
                            <td>{asRunTime(row.timestamp_ms)}</td>
                            <td className="ui-mono">
                              {String(row.name ?? row.job_id ?? "unknown")}
                            </td>
                            <td>{String(row.status ?? "ok")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </TableWrap>
                </>
              )}
            </div>
          </div>
          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Recent Failures</h2>
              <Badge tone="warn">{recentFailures.length}</Badge>
            </div>
            <div className="p-3">
              {loading ? (
                <div className="space-y-2">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ) : recentFailures.length === 0 ? (
                <EmptyState
                  title="No Failures"
                  description="No recent scheduler failures."
                />
              ) : (
                <>
                  <div className="space-y-2 md:hidden">
                    {recentFailures.map((row, idx) => (
                      <article
                        key={`${idx}-failures-mobile`}
                        className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm"
                      >
                        <div className="ui-mono text-sm">
                          {String(row.name ?? row.job_id ?? "unknown")}
                        </div>
                        <div className="mt-1 text-xs text-[var(--muted)]">
                          {asRunTime(row.timestamp_ms)}
                        </div>
                        <div className="mt-2 text-xs text-[var(--danger)]">
                          {String(row.error ?? "error")}
                        </div>
                      </article>
                    ))}
                  </div>
                  <TableWrap className="hidden max-h-[320px] md:block">
                    <DataTable>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Job</th>
                          <th>Error</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentFailures.map((row, idx) => (
                          <tr key={idx}>
                            <td>{asRunTime(row.timestamp_ms)}</td>
                            <td className="ui-mono">
                              {String(row.name ?? row.job_id ?? "unknown")}
                            </td>
                            <td>{String(row.error ?? "error")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </TableWrap>
                </>
              )}
            </div>
          </div>
          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Heartbeat Runs</h2>
              <Badge tone="neutral">{recentHeartbeat.length}</Badge>
            </div>
            <div className="p-3">
              {loading ? (
                <div className="space-y-2">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ) : recentHeartbeat.length === 0 ? (
                <EmptyState
                  title="No Heartbeat Runs"
                  description="No heartbeat records have been captured yet."
                />
              ) : (
                <>
                  <div className="space-y-2 md:hidden">
                    {recentHeartbeat.map((row, idx) => (
                      <article
                        key={`${idx}-heartbeat-mobile`}
                        className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span>{String(row.status ?? "unknown")}</span>
                          <span className="text-xs text-[var(--muted)]">
                            {asRunTime(row.timestamp_ms)}
                          </span>
                        </div>
                        <div className="mt-2 text-xs text-[var(--muted)]">
                          {String(
                            (
                              row.details as
                                | { response_preview?: string }
                                | undefined
                            )?.response_preview ?? "",
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                  <TableWrap className="hidden max-h-[320px] md:block">
                    <DataTable>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Status</th>
                          <th>Info</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentHeartbeat.map((row, idx) => (
                          <tr key={idx}>
                            <td>{asRunTime(row.timestamp_ms)}</td>
                            <td>{String(row.status ?? "unknown")}</td>
                            <td>
                              {String(
                                (
                                  row.details as
                                    | { response_preview?: string }
                                    | undefined
                                )?.response_preview ?? "",
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </TableWrap>
                </>
              )}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
