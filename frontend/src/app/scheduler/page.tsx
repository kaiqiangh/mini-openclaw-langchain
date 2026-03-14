"use client";

import { useEffect, useMemo, useState } from "react";

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
  DismissibleHint,
  MetricCard,
  MetricGrid,
  PageHeader,
  PageLayout,
  PageStack,
} from "@/components/ui/page-shell";
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
import { usePersistentSectionState } from "@/lib/usePersistentSectionState";

type ScheduleType = "at" | "every" | "cron";
type SchedulerSectionKey =
  | "metrics"
  | "trend"
  | "cron"
  | "heartbeat"
  | "recent_runs"
  | "recent_failures"
  | "heartbeat_runs";
type JobStatusFilter =
  | "all"
  | "scheduled"
  | "retrying"
  | "paused"
  | "completed"
  | "failed";
type StatusTone = "neutral" | "accent" | "success" | "warn" | "danger";
type DerivedJobStatus = {
  key: Exclude<JobStatusFilter, "all">;
  label: string;
  tone: StatusTone;
  detail: string;
};

const SCHEDULER_SECTIONS_KEY = "mini-openclaw:scheduler-sections:v1";
const DESKTOP_SCHEDULER_SECTIONS: Record<SchedulerSectionKey, boolean> = {
  metrics: true,
  trend: true,
  cron: true,
  heartbeat: true,
  recent_runs: true,
  recent_failures: true,
  heartbeat_runs: true,
};
const MOBILE_SCHEDULER_SECTIONS: Record<SchedulerSectionKey, boolean> = {
  metrics: true,
  trend: true,
  cron: false,
  heartbeat: false,
  recent_runs: false,
  recent_failures: false,
  heartbeat_runs: false,
};

const SCHEDULER_METRIC_GRID_STYLE = {
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
} as const;
const CRON_EDITOR_GRID_STYLE = {
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
} as const;

const SCHEDULER_DATA_PANEL_CLASS = "max-h-[26rem] overflow-y-auto lg:max-h-[40vh]";
const CRON_STATUS_OPTIONS: Array<{
  label: string;
  value: JobStatusFilter;
}> = [
  { label: "All states", value: "all" },
  { label: "Scheduled", value: "scheduled" },
  { label: "Retrying", value: "retrying" },
  { label: "Paused", value: "paused" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
];

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

function describeSchedule(type: ScheduleType, value: string): string {
  const normalized = value.trim();
  if (!normalized) return "Enter a schedule value.";
  if (type === "every") {
    const seconds = Number(normalized);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return "Interval must be a positive number of seconds.";
    }
    return `Runs every ${seconds} seconds.`;
  }
  if (type === "at") {
    const parsed = Date.parse(normalized);
    if (Number.isNaN(parsed)) {
      return "Use an ISO datetime, e.g. 2026-03-01T10:00:00Z.";
    }
    return `Runs once at ${new Date(parsed).toLocaleString()}.`;
  }
  return "Cron expression with 5 fields (minute hour day month weekday).";
}

function formatEveryInterval(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    return `${hours}h`;
  }
  if (seconds % 60 === 0) {
    const minutes = seconds / 60;
    return `${minutes}m`;
  }
  return `${seconds}s`;
}

function formatScheduleSummary(type: ScheduleType, value: string): string {
  const normalized = value.trim();
  if (!normalized) return "Schedule required";
  if (type === "every") {
    const seconds = Number(normalized);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return "Invalid interval";
    }
    return `Every ${formatEveryInterval(seconds)}`;
  }
  if (type === "at") {
    const parsed = Date.parse(normalized);
    if (Number.isNaN(parsed)) {
      return "One-time run";
    }
    return `Once at ${new Date(parsed).toLocaleString()}`;
  }
  return `Cron ${normalized}`;
}

function previewText(value: string, maxLength = 96): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return "—";
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1)}…`;
}

function deriveJobStatus(job: CronJob): DerivedJobStatus {
  const hasError = job.last_error.trim().length > 0;
  const hasRun = Number(job.last_run_ts) > 0;
  const futureRun = Number(job.next_run_ts) > 0;

  if (job.enabled && job.failure_count > 0 && hasError) {
    return {
      key: "retrying",
      label: "Retrying",
      tone: "warn",
      detail: futureRun
        ? `Retry queued for ${asDateTime(job.next_run_ts)}`
        : "Retry queued on next scheduler tick",
    };
  }
  if (job.enabled) {
    return {
      key: "scheduled",
      label: "Scheduled",
      tone: "success",
      detail: futureRun
        ? `Next run ${asDateTime(job.next_run_ts)}`
        : "Waiting for the next scheduler tick",
    };
  }
  if (job.schedule_type === "at" && hasRun && !hasError) {
    return {
      key: "completed",
      label: "Completed",
      tone: "accent",
      detail: `Finished ${asDateTime(job.last_run_ts)}`,
    };
  }
  if (hasError) {
    return {
      key: "failed",
      label: "Failed",
      tone: "danger",
      detail: previewText(job.last_error, 120),
    };
  }
  return {
    key: "paused",
    label: "Paused",
    tone: "neutral",
    detail: hasRun ? `Paused after ${asDateTime(job.last_run_ts)}` : "Disabled by operator",
  };
}

export default function SchedulerPage() {
  const { currentAgentId, setCurrentAgent } = useAppStore();
  const [agents, setAgents] = useState<string[]>(["default"]);
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
  const [density, setDensity] = useState<"comfortable" | "compact">(
    "comfortable",
  );
  const [jobStatusFilter, setJobStatusFilter] = useState<JobStatusFilter>("all");
  const [editorOpen, setEditorOpen] = useState(false);
  const [savingJob, setSavingJob] = useState(false);
  const [jobActionKey, setJobActionKey] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<CronJob | null>(null);
  const { sections, toggleSection, expandAll, collapseAll } =
    usePersistentSectionState<SchedulerSectionKey>({
      storageKey: SCHEDULER_SECTIONS_KEY,
      desktopDefaults: DESKTOP_SCHEDULER_SECTIONS,
      mobileDefaults: MOBILE_SCHEDULER_SECTIONS,
    });
  const agentId = currentAgentId;

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem("mini-openclaw:scheduler-density");
    if (saved === "compact" || saved === "comfortable") {
      setDensity(saved);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("mini-openclaw:scheduler-density", density);
  }, [density]);

  async function refreshAll(
    nextAgentId: string,
    window: SchedulerMetricsWindow,
  ): Promise<CronJob[]> {
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
      return jobRows;
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load scheduler data",
      );
      return [];
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
        if (!safeIds.includes(currentAgentId)) {
          void setCurrentAgent(safeIds[0] ?? "default");
        }
      } catch {
        if (!cancelled) {
          setAgents(["default"]);
        }
      }
    }
    void loadAgents();
    return () => {
      cancelled = true;
    };
  }, [currentAgentId, setCurrentAgent]);

  useEffect(() => {
    void refreshAll(agentId, metricsWindow);
  }, [agentId, metricsWindow]);

  function openJobEditor(job?: CronJob | null) {
    setDraft(
      job
        ? {
            id: job.id,
            name: job.name,
            schedule_type: job.schedule_type,
            schedule: job.schedule,
            prompt: job.prompt,
            enabled: job.enabled,
          }
        : EMPTY_DRAFT,
    );
    setSubmitAttempted(false);
    setError("");
    setSelectedJob(null);
    setEditorOpen(true);
  }

  function closeJobEditor() {
    setEditorOpen(false);
    setDraft(EMPTY_DRAFT);
    setSubmitAttempted(false);
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (editorOpen) {
          closeJobEditor();
          return;
        }
        setSelectedJob(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [editorOpen]);

  const recentRuns = useMemo(() => runs.slice(0, 10), [runs]);
  const recentFailures = useMemo(() => failures.slice(0, 10), [failures]);
  const recentHeartbeat = useMemo(
    () => heartbeatRuns.slice(0, 10),
    [heartbeatRuns],
  );
  const orderedJobs = useMemo(
    () =>
      [...jobs].sort((left, right) => {
        const leftNext = Number(left.next_run_ts) || 0;
        const rightNext = Number(right.next_run_ts) || 0;
        if (leftNext > 0 && rightNext > 0 && leftNext !== rightNext) {
          return leftNext - rightNext;
        }
        if (right.updated_at !== left.updated_at) {
          return right.updated_at - left.updated_at;
        }
        return left.name.localeCompare(right.name);
      }),
    [jobs],
  );
  const filteredJobs = useMemo(
    () =>
      orderedJobs.filter((job) => {
        if (jobStatusFilter === "all") {
          return true;
        }
        return deriveJobStatus(job).key === jobStatusFilter;
      }),
    [jobStatusFilter, orderedJobs],
  );
  const jobStatusCounts = useMemo(() => {
    return jobs.reduce(
      (acc, job) => {
        const key = deriveJobStatus(job).key;
        acc[key] += 1;
        return acc;
      },
      {
        scheduled: 0,
        retrying: 0,
        paused: 0,
        completed: 0,
        failed: 0,
      },
    );
  }, [jobs]);
  const trendPoints = useMemo(() => metricsSeries?.points ?? [], [metricsSeries]);
  const trendMax = useMemo(
    () => Math.max(1, ...trendPoints.map((point) => point.total)),
    [trendPoints],
  );
  const scheduleHint = useMemo(
    () => describeSchedule(draft.schedule_type, draft.schedule),
    [draft.schedule, draft.schedule_type],
  );
  const draftStatusPreview = useMemo(() => {
    if (!draft.id) {
      return "New jobs start clean and inherit the selected active state.";
    }
    const currentJob =
      jobs.find((job) => job.id === draft.id) ??
      ({
        id: draft.id,
        name: draft.name,
        schedule_type: draft.schedule_type,
        schedule: draft.schedule,
        prompt: draft.prompt,
        enabled: draft.enabled,
        next_run_ts: 0,
        created_at: 0,
        updated_at: 0,
        last_run_ts: 0,
        last_success_ts: 0,
        failure_count: 0,
        last_error: "",
      } satisfies CronJob);
    return `Current state: ${deriveJobStatus(currentJob).label}`;
  }, [draft, jobs]);
  const heartbeatHealth = useMemo(() => {
    const latest = recentHeartbeat[0];
    const ts = Number(latest?.timestamp_ms ?? 0);
    if (!Number.isFinite(ts) || ts <= 0) return "unknown";
    const ageMs = Date.now() - ts;
    const staleAfterMs = Math.max(60, heartbeat.interval_seconds * 2) * 1000;
    return ageMs > staleAfterMs ? "stale" : "healthy";
  }, [heartbeat.interval_seconds, recentHeartbeat]);

  async function handleSubmitJob() {
    setSubmitAttempted(true);
    if (!draft.prompt.trim() || !draft.schedule.trim()) {
      setError("Schedule and prompt are required.");
      return;
    }
    setError("");
    setSavingJob(true);
    try {
      const savedJob = draft.id
        ? await updateCronJob(
            draft.id,
            {
              name: draft.name,
              schedule_type: draft.schedule_type,
              schedule: draft.schedule,
              prompt: draft.prompt,
              enabled: draft.enabled,
            },
            agentId,
          )
        : await createCronJob(
            {
              name: draft.name,
              schedule_type: draft.schedule_type,
              schedule: draft.schedule,
              prompt: draft.prompt,
              enabled: draft.enabled,
            },
            agentId,
          );
      closeJobEditor();
      const refreshedJobs = await refreshAll(agentId, metricsWindow);
      setSelectedJob(
        refreshedJobs.find((job) => job.id === savedJob.id) ?? savedJob,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save cron job");
    } finally {
      setSavingJob(false);
    }
  }

  async function handleJobAction(
    job: CronJob,
    action: "toggle" | "run" | "delete",
  ) {
    const actionKey = `${job.id}:${action}`;
    setJobActionKey(actionKey);
    setError("");
    try {
      if (action === "toggle") {
        await updateCronJob(job.id, { enabled: !job.enabled }, agentId);
      } else if (action === "run") {
        await runCronJob(job.id, agentId);
      } else {
        await deleteCronJob(job.id, agentId);
      }
      if (action === "delete") {
        setSelectedJob((current) => (current?.id === job.id ? null : current));
      }
      const refreshedJobs = await refreshAll(agentId, metricsWindow);
      if (action !== "delete" && selectedJob?.id === job.id) {
        setSelectedJob(
          refreshedJobs.find((item) => item.id === job.id) ?? null,
        );
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update cron job",
      );
    } finally {
      setJobActionKey(null);
    }
  }

  return (
    <PageLayout>
      <PageStack>
        <PageHeader
          eyebrow="Scheduler"
          title="Scheduler"
          description="Monitor cron jobs, heartbeat health, and operational latency from a single control surface."
          meta={
            <>
              {loading ? (
                <Badge tone="accent">Loading</Badge>
              ) : (
                <Badge tone="success">Ready</Badge>
              )}
              {error ? <Badge tone="danger">Error</Badge> : null}
              <Badge tone="neutral">Agent {agentId}</Badge>
              <Badge tone="neutral">{jobs.length} jobs</Badge>
            </>
          }
          actions={
            <>
              <Button
                type="button"
                size="sm"
                className="px-3"
                onClick={() => openJobEditor()}
              >
                New Job
              </Button>
              <Button
                type="button"
                size="sm"
                className="px-2"
                onClick={expandAll}
              >
                Expand All Sections
              </Button>
              <Button
                type="button"
                size="sm"
                className="px-2"
                onClick={collapseAll}
              >
                Collapse All Sections
              </Button>
            </>
          }
        />

        <DismissibleHint
          storageKey="mini-openclaw:scheduler-hint:v1"
          title="Section memory"
          description="Scheduler sections remember their expanded state. Collapse low-signal areas on smaller screens and keep metrics or cron controls open while you work."
        />

        <div className="panel-shell">
          <div className="ui-panel-header">
            <h1 className="ui-panel-title">Filters</h1>
            <div className="flex w-full flex-wrap items-center justify-end gap-2 lg:w-auto">
              <Select
                aria-label="Scheduler agent switch"
                className="ui-mono min-h-[44px] w-full text-sm sm:w-[160px]"
                value={agentId}
                onChange={(event) => {
                  void setCurrentAgent(event.target.value);
                }}
              >
                {agents.map((id) => (
                  <option key={`header-${id}`} value={id}>
                    {id}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Scheduler metrics window"
                className="min-h-[44px] w-full text-sm sm:w-[92px]"
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
              <Select
                aria-label="Scheduler density"
                className="min-h-[44px] w-full text-sm sm:w-[120px]"
                value={density}
                onChange={(event) =>
                  setDensity(event.target.value as "comfortable" | "compact")
                }
              >
                <option value="comfortable">Comfortable</option>
                <option value="compact">Compact</option>
              </Select>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm text-[var(--muted)]">
            <span>{jobs.length} jobs</span>
            <span>·</span>
            <span>{jobStatusCounts.scheduled} scheduled</span>
            <span>·</span>
            <span>{jobStatusCounts.retrying} retrying</span>
            <span>·</span>
            <span>{jobStatusCounts.paused} paused</span>
            <span>·</span>
            <span>{jobStatusCounts.failed} failed</span>
          </div>
          {error ? (
            <div className="px-4 pb-4">
              <div className="ui-alert" role="alert">
                {error}
              </div>
            </div>
          ) : null}
        </div>

        <div className="panel-shell min-w-0">
          <div className="ui-panel-header">
            <h2 className="ui-panel-title">Scheduler Metrics</h2>
            <Button
              type="button"
              size="sm"
              className="px-2"
              aria-expanded={sections.metrics}
              onClick={() => toggleSection("metrics")}
            >
              {sections.metrics ? "Collapse" : "Expand"}
            </Button>
          </div>
          {sections.metrics ? (
            <div className="p-4">
              <MetricGrid style={SCHEDULER_METRIC_GRID_STYLE}>
                <MetricCard
                  label="Scheduler Events"
                  value={metrics?.totals.events ?? 0}
                  meta={`Cron ${metrics?.totals.cron_events ?? 0} · Heartbeat ${metrics?.totals.heartbeat_events ?? 0}`}
                  tone="accent"
                />
                <MetricCard
                  label="Cron Success Rate"
                  value={`${metrics?.cron.success_rate ?? 0}%`}
                  meta={`ok ${metrics?.cron.ok ?? 0} · error ${metrics?.cron.error ?? 0}`}
                />
                <MetricCard
                  label="Duration p90 / p99"
                  value={`${asMs(metrics?.duration.p90_ms)} / ${asMs(metrics?.duration.p99_ms)}`}
                  meta={`avg ${asMs(metrics?.duration.avg_ms)} · max ${asMs(metrics?.duration.max_ms)}`}
                  tone="signal"
                />
                <MetricCard
                  label="Latency p90 / p99"
                  value={`${asMs(metrics?.latency.p90_ms)} / ${asMs(metrics?.latency.p99_ms)}`}
                  meta={`avg ${asMs(metrics?.latency.avg_ms)} · max ${asMs(metrics?.latency.max_ms)}`}
                />
              </MetricGrid>
            </div>
          ) : null}
        </div>

        <div className="panel-shell min-w-0">
          <div className="ui-panel-header">
            <h2 className="ui-panel-title">Observability Trend</h2>
            <div className="flex items-center gap-2">
              <Badge tone="neutral">
                {metricsSeries?.points.length ?? 0} buckets
              </Badge>
              <Button
                type="button"
                size="sm"
                className="px-2"
                aria-expanded={sections.trend}
                onClick={() => toggleSection("trend")}
              >
                {sections.trend ? "Collapse" : "Expand"}
              </Button>
            </div>
          </div>
          {sections.trend ? (
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
                    {trendPoints
                      .slice(Math.max(0, trendPoints.length - 8))
                      .map((point) => (
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
          ) : null}
        </div>

        <div className="grid min-w-0 gap-3 lg:grid-cols-3">
          <div className="panel-shell min-w-0 lg:col-span-2">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Cron Jobs</h2>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">
                  {filteredJobs.length}/{jobs.length} shown
                </Badge>
                <Select
                  aria-label="Filter cron jobs by state"
                  className="min-h-[40px] w-full text-sm sm:w-[160px]"
                  value={jobStatusFilter}
                  onChange={(event) =>
                    setJobStatusFilter(event.target.value as JobStatusFilter)
                  }
                >
                  {CRON_STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <Button
                  type="button"
                  size="sm"
                  className="px-2"
                  onClick={() => openJobEditor()}
                >
                  New Job
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="px-2"
                  aria-expanded={sections.cron}
                  onClick={() => toggleSection("cron")}
                >
                  {sections.cron ? "Collapse" : "Expand"}
                </Button>
              </div>
            </div>
            {sections.cron ? (
              <div className="p-3">
                {loading ? (
                  <div className="space-y-2">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                  </div>
                ) : jobs.length === 0 ? (
                  <div className="space-y-3">
                    <EmptyState
                      title="No Cron Jobs"
                      description="Create a cron job to start scheduled automation."
                    />
                    <Button type="button" onClick={() => openJobEditor()}>
                      Create Job
                    </Button>
                  </div>
                ) : filteredJobs.length === 0 ? (
                  <EmptyState
                    title="No Matching Jobs"
                    description="Try a different state filter or create a new job."
                  />
                ) : (
                  <div
                    className={SCHEDULER_DATA_PANEL_CLASS}
                    data-testid="scheduler-cron-scroll"
                  >
                    <div className="space-y-2 lg:hidden">
                      {filteredJobs.map((job) => {
                        const status = deriveJobStatus(job);
                        const runBusy = jobActionKey === `${job.id}:run`;
                        const toggleBusy = jobActionKey === `${job.id}:toggle`;
                        const deleteBusy = jobActionKey === `${job.id}:delete`;
                        return (
                          <article
                            key={`${job.id}-mobile`}
                            className="cursor-pointer rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm"
                            onClick={() => setSelectedJob(job)}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="ui-mono truncate">
                                  {job.name || job.id.slice(0, 8)}
                                </div>
                                <div className="mt-1 text-xs text-[var(--muted)]">
                                  {formatScheduleSummary(
                                    job.schedule_type,
                                    job.schedule,
                                  )}
                                </div>
                              </div>
                              <Badge tone={status.tone}>{status.label}</Badge>
                            </div>
                            <div className="mt-3 grid gap-2 text-xs text-[var(--muted)]">
                              <div>{status.detail}</div>
                              <div>
                                Last run {asDateTime(job.last_run_ts)} · success{" "}
                                {asDateTime(job.last_success_ts)}
                              </div>
                              <div>
                                Prompt: {previewText(job.prompt, 84)}
                              </div>
                              {job.last_error ? (
                                <div className="rounded-md border border-[var(--border)] bg-[var(--danger-soft)] px-2 py-1 text-[var(--danger)]">
                                  {previewText(job.last_error, 120)}
                                </div>
                              ) : null}
                            </div>
                            <div className="mt-3 flex flex-wrap gap-1">
                              <Button
                                type="button"
                                size="sm"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openJobEditor(job);
                                }}
                              >
                                Edit
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                loading={runBusy}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleJobAction(job, "run");
                                }}
                              >
                                Run now
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                loading={toggleBusy}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleJobAction(job, "toggle");
                                }}
                              >
                                {job.enabled ? "Pause" : "Resume"}
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="danger"
                                loading={deleteBusy}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleJobAction(job, "delete");
                                }}
                              >
                                Delete
                              </Button>
                            </div>
                          </article>
                        );
                      })}
                    </div>
                    <TableWrap className="hidden lg:block">
                      <DataTable
                        className={density === "compact" ? "ui-table-compact" : ""}
                      >
                        <thead>
                          <tr>
                            <th>Name</th>
                            <th>Schedule</th>
                            <th>Status</th>
                            <th>Next Run</th>
                            <th>Last Run</th>
                            <th>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredJobs.map((job) => {
                            const status = deriveJobStatus(job);
                            const runBusy = jobActionKey === `${job.id}:run`;
                            const toggleBusy = jobActionKey === `${job.id}:toggle`;
                            const deleteBusy = jobActionKey === `${job.id}:delete`;
                            return (
                              <tr
                                key={job.id}
                                className="cursor-pointer"
                                onClick={() => setSelectedJob(job)}
                              >
                                <td className="ui-mono">
                                  <div>{job.name || job.id.slice(0, 8)}</div>
                                  <div className="mt-1 text-xs text-[var(--muted)]">
                                    {previewText(job.prompt, 80)}
                                  </div>
                                </td>
                                <td>
                                  <div className="ui-mono">
                                    {formatScheduleSummary(
                                      job.schedule_type,
                                      job.schedule,
                                    )}
                                  </div>
                                  <div className="mt-1 text-xs text-[var(--muted)]">
                                    {job.schedule_type === "cron"
                                      ? "Raw expression available in detail view"
                                      : describeSchedule(
                                          job.schedule_type,
                                          job.schedule,
                                        )}
                                  </div>
                                </td>
                                <td>
                                  <div className="flex flex-col gap-1">
                                    <Badge tone={status.tone}>{status.label}</Badge>
                                    <span className="text-xs text-[var(--muted)]">
                                      {status.detail}
                                    </span>
                                  </div>
                                </td>
                                <td>{asDateTime(job.next_run_ts)}</td>
                                <td>
                                  <div>{asDateTime(job.last_run_ts)}</div>
                                  <div className="mt-1 text-xs text-[var(--muted)]">
                                    success {asDateTime(job.last_success_ts)}
                                  </div>
                                </td>
                                <td>
                                  <div className="flex flex-wrap gap-1">
                                    <Button
                                      type="button"
                                      size="sm"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        openJobEditor(job);
                                      }}
                                    >
                                      Edit
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      loading={runBusy}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        void handleJobAction(job, "run");
                                      }}
                                    >
                                      Run now
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      loading={toggleBusy}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        void handleJobAction(job, "toggle");
                                      }}
                                    >
                                      {job.enabled ? "Pause" : "Resume"}
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="danger"
                                      loading={deleteBusy}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        void handleJobAction(job, "delete");
                                      }}
                                    >
                                      Delete
                                    </Button>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </DataTable>
                    </TableWrap>
                  </div>
                )}
              </div>
            ) : null}
          </div>

          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Heartbeat</h2>
              <div className="flex items-center gap-1">
                <Badge tone={heartbeat.enabled ? "success" : "warn"}>
                  {heartbeat.enabled ? "Enabled" : "Disabled"}
                </Badge>
                <Badge
                  tone={
                    heartbeatHealth === "healthy"
                      ? "success"
                      : heartbeatHealth === "stale"
                        ? "warn"
                        : "neutral"
                  }
                >
                  {heartbeatHealth}
                </Badge>
                <Button
                  type="button"
                  size="sm"
                  className="px-2"
                  aria-expanded={sections.heartbeat}
                  onClick={() => toggleSection("heartbeat")}
                >
                  {sections.heartbeat ? "Collapse" : "Expand"}
                </Button>
              </div>
            </div>
            {sections.heartbeat ? (
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
            ) : null}
          </div>
        </div>

        <div className="grid min-w-0 gap-3 lg:grid-cols-3">
          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Recent Runs</h2>
              <div className="flex items-center gap-2">
                <Badge tone="neutral">{recentRuns.length}</Badge>
                <Button
                  type="button"
                  size="sm"
                  className="px-2"
                  aria-expanded={sections.recent_runs}
                  onClick={() => toggleSection("recent_runs")}
                >
                  {sections.recent_runs ? "Collapse" : "Expand"}
                </Button>
              </div>
            </div>
            {sections.recent_runs ? <div className="p-3">
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
                  <div
                    className={SCHEDULER_DATA_PANEL_CLASS}
                    data-testid="scheduler-recent-runs-scroll"
                  >
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
                    <TableWrap className="hidden md:block">
                      <DataTable
                        className={density === "compact" ? "ui-table-compact" : ""}
                      >
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
                  </div>
              )}
            </div> : null}
          </div>
          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Recent Failures</h2>
              <div className="flex items-center gap-2">
                <Badge tone="warn">{recentFailures.length}</Badge>
                <Button
                  type="button"
                  size="sm"
                  className="px-2"
                  aria-expanded={sections.recent_failures}
                  onClick={() => toggleSection("recent_failures")}
                >
                  {sections.recent_failures ? "Collapse" : "Expand"}
                </Button>
              </div>
            </div>
            {sections.recent_failures ? <div className="p-3">
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
                  <div
                    className={SCHEDULER_DATA_PANEL_CLASS}
                    data-testid="scheduler-recent-failures-scroll"
                  >
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
                    <TableWrap className="hidden md:block">
                      <DataTable
                        className={density === "compact" ? "ui-table-compact" : ""}
                      >
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
                  </div>
              )}
            </div> : null}
          </div>
          <div className="panel-shell min-w-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Heartbeat Runs</h2>
              <div className="flex items-center gap-2">
                <Badge tone="neutral">{recentHeartbeat.length}</Badge>
                <Button
                  type="button"
                  size="sm"
                  className="px-2"
                  aria-expanded={sections.heartbeat_runs}
                  onClick={() => toggleSection("heartbeat_runs")}
                >
                  {sections.heartbeat_runs ? "Collapse" : "Expand"}
                </Button>
              </div>
            </div>
            {sections.heartbeat_runs ? <div className="p-3">
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
                  <div
                    className={SCHEDULER_DATA_PANEL_CLASS}
                    data-testid="scheduler-heartbeat-runs-scroll"
                  >
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
                    <TableWrap className="hidden md:block">
                      <DataTable
                        className={density === "compact" ? "ui-table-compact" : ""}
                      >
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
                  </div>
              )}
            </div> : null}
          </div>
        </div>
        {selectedJob ? (
          <div
            className="fixed inset-0 z-50 bg-[rgba(2,6,23,0.36)] backdrop-blur-[1px]"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                setSelectedJob(null);
              }
            }}
          >
            <aside className="ui-drawer ml-auto flex h-full w-full max-w-[min(560px,100vw)] flex-col rounded-none border-l border-[var(--border-strong)] bg-[var(--surface-1)] shadow-2xl">
              <div className="ui-panel-header">
                <div>
                  <h2 className="ui-panel-title">Cron Job Detail</h2>
                  <div className="mt-1 text-xs text-[var(--muted)]">
                    Quick view for schedule state, last activity, and prompt.
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => setSelectedJob(null)}
                >
                  Close
                </Button>
              </div>
              <div className="ui-scroll-area flex-1 space-y-3 p-4 text-sm">
                {(() => {
                  const status = deriveJobStatus(selectedJob);
                  const runBusy = jobActionKey === `${selectedJob.id}:run`;
                  const toggleBusy = jobActionKey === `${selectedJob.id}:toggle`;
                  const deleteBusy = jobActionKey === `${selectedJob.id}:delete`;
                  return (
                    <>
                      <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="ui-label">Job</div>
                            <div className="ui-mono mt-1">
                              {selectedJob.name || selectedJob.id.slice(0, 8)}
                            </div>
                          </div>
                          <Badge tone={status.tone}>{status.label}</Badge>
                        </div>
                        <div className="mt-2 text-xs text-[var(--muted)]">
                          {status.detail}
                        </div>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                          <div className="ui-label">Schedule</div>
                          <div className="ui-mono mt-1">
                            {formatScheduleSummary(
                              selectedJob.schedule_type,
                              selectedJob.schedule,
                            )}
                          </div>
                          <div className="mt-1 text-xs text-[var(--muted)]">
                            {selectedJob.schedule_type === "cron"
                              ? selectedJob.schedule
                              : describeSchedule(
                                  selectedJob.schedule_type,
                                  selectedJob.schedule,
                                )}
                          </div>
                        </div>
                        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                          <div className="ui-label">Timing</div>
                          <div className="mt-1 text-xs text-[var(--muted)]">
                            Next run {asDateTime(selectedJob.next_run_ts)}
                          </div>
                          <div className="mt-1 text-xs text-[var(--muted)]">
                            Last run {asDateTime(selectedJob.last_run_ts)}
                          </div>
                          <div className="mt-1 text-xs text-[var(--muted)]">
                            Last success {asDateTime(selectedJob.last_success_ts)}
                          </div>
                        </div>
                      </div>
                      <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                        <div className="ui-label">Prompt</div>
                        <pre className="ui-mono mt-2 whitespace-pre-wrap text-xs text-[var(--text)]">
                          {selectedJob.prompt}
                        </pre>
                      </div>
                      {selectedJob.last_error ? (
                        <div className="rounded-md border border-[var(--border)] bg-[var(--danger-soft)] p-3">
                          <div className="ui-label text-[var(--danger)]">
                            Last Error
                          </div>
                          <div className="mt-2 whitespace-pre-wrap text-sm text-[var(--danger)]">
                            {selectedJob.last_error}
                          </div>
                        </div>
                      ) : null}
                      <div className="flex flex-wrap gap-2">
                        <Button
                          type="button"
                          size="sm"
                          loading={runBusy}
                          onClick={() => void handleJobAction(selectedJob, "run")}
                        >
                          Run now
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          loading={toggleBusy}
                          onClick={() =>
                            void handleJobAction(selectedJob, "toggle")
                          }
                        >
                          {selectedJob.enabled ? "Pause" : "Resume"}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => openJobEditor(selectedJob)}
                        >
                          Edit
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="danger"
                          loading={deleteBusy}
                          onClick={() => void handleJobAction(selectedJob, "delete")}
                        >
                          Delete
                        </Button>
                      </div>
                    </>
                  );
                })()}
              </div>
            </aside>
          </div>
        ) : null}
        {editorOpen ? (
          <div
            className="fixed inset-0 z-50 bg-[rgba(2,6,23,0.42)] backdrop-blur-[2px]"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeJobEditor();
              }
            }}
          >
            <aside
              className="ui-drawer ml-auto flex h-full w-full max-w-[min(620px,100vw)] flex-col rounded-none border-l border-[var(--border-strong)] bg-[var(--surface-2)] shadow-2xl"
              role="dialog"
              aria-modal="true"
              aria-labelledby="cron-job-editor-title"
              data-testid="scheduler-job-editor"
            >
              <div className="ui-panel-header">
                <div>
                  <h2 id="cron-job-editor-title" className="ui-panel-title">
                    {draft.id ? "Edit Cron Job" : "Create Cron Job"}
                  </h2>
                  <div className="mt-1 text-xs text-[var(--muted)]">
                    Set what runs, when it runs, and whether it starts active.
                  </div>
                </div>
                <Button type="button" size="sm" onClick={closeJobEditor}>
                  Close
                </Button>
              </div>
              <div className="ui-scroll-area flex-1 space-y-4 p-4">
                <div className="grid gap-4" style={CRON_EDITOR_GRID_STYLE}>
                  <label className="min-w-0">
                    <span className="ui-label">Job Name</span>
                    <Input
                      className="mt-1 text-sm"
                      value={draft.name}
                      onChange={(event) =>
                        setDraft((prev) => ({ ...prev, name: event.target.value }))
                      }
                      placeholder="Operator-friendly label"
                    />
                    <span className="ui-helper mt-1 block">
                      Leave blank to use a generated cron identifier.
                    </span>
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
                      <option value="every">Every interval</option>
                      <option value="cron">Cron expression</option>
                      <option value="at">One-time run</option>
                    </Select>
                    <span className="ui-helper mt-1 block">
                      Default to interval mode unless you need calendar precision.
                    </span>
                  </label>
                  <label className="min-w-0">
                    <span className="ui-label">When It Runs</span>
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
                            ? "*/15 * * * *"
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
                        : scheduleHint}
                    </span>
                  </label>
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                    <div className="ui-label">Runtime Preview</div>
                    <div className="mt-1 text-sm text-[var(--text)]">
                      {formatScheduleSummary(draft.schedule_type, draft.schedule)}
                    </div>
                    <div className="mt-2 text-xs text-[var(--muted)]">
                      {draftStatusPreview}
                    </div>
                  </div>
                </div>
                <label className="block">
                  <span className="ui-label">Prompt</span>
                  <textarea
                    className="ui-input mt-1 min-h-[160px] resize-y text-sm"
                    aria-invalid={
                      submitAttempted && !draft.prompt.trim() ? true : undefined
                    }
                    value={draft.prompt}
                    onChange={(event) =>
                      setDraft((prev) => ({ ...prev, prompt: event.target.value }))
                    }
                    placeholder="Describe exactly what the job should do when it runs."
                  />
                  <span className="ui-helper mt-1 block">
                    Keep the prompt task-focused. Tooling guidance is added by the scheduler runtime.
                  </span>
                </label>
                <label className="flex min-h-[44px] items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-3 text-sm text-[var(--muted)]">
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
                  Start this job active after saving
                </label>
              </div>
              <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--border)] bg-[var(--surface-header)] px-4 py-3">
                <Button type="button" size="sm" onClick={closeJobEditor}>
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  loading={savingJob}
                  onClick={() => void handleSubmitJob()}
                >
                  {draft.id ? "Save Changes" : "Create Job"}
                </Button>
              </div>
            </aside>
          </div>
        ) : null}
      </PageStack>
    </PageLayout>
  );
}
