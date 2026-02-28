"use client";

import { useEffect, useMemo, useState } from "react";

import { Navbar } from "@/components/layout/Navbar";
import {
  Badge,
  Button,
  DataTable,
  Input,
  Select,
  TableWrap,
} from "@/components/ui/primitives";
import {
  createCronJob,
  CronJob,
  deleteCronJob,
  getAgents,
  getHeartbeatConfig,
  HeartbeatConfig,
  listCronFailures,
  listCronJobs,
  listCronRuns,
  listHeartbeatRuns,
  runCronJob,
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

export default function SchedulerPage() {
  const { currentAgentId } = useAppStore();
  const [agents, setAgents] = useState<string[]>(["default"]);
  const [agentId, setAgentId] = useState<string>(currentAgentId || "default");
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);
  const [failures, setFailures] = useState<Array<Record<string, unknown>>>([]);
  const [heartbeatRuns, setHeartbeatRuns] = useState<
    Array<Record<string, unknown>>
  >([]);
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

  async function refreshAll(nextAgentId: string) {
    setLoading(true);
    setError("");
    try {
      const [jobRows, runRows, failureRows, heartbeatConfig, heartbeatRunRows] =
        await Promise.all([
          listCronJobs(nextAgentId),
          listCronRuns(nextAgentId, 100),
          listCronFailures(nextAgentId, 100),
          getHeartbeatConfig(nextAgentId),
          listHeartbeatRuns(nextAgentId, 100),
        ]);
      setJobs(jobRows);
      setRuns(runRows);
      setFailures(failureRows);
      setHeartbeat(heartbeatConfig);
      setHeartbeatRuns(heartbeatRunRows);
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
        setAgents(ids.length ? ids : ["default"]);
        if (ids.length && !ids.includes(agentId)) {
          setAgentId(ids[0]);
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
  }, [agentId]);

  useEffect(() => {
    void refreshAll(agentId);
  }, [agentId]);

  useEffect(() => {
    if (!currentAgentId) return;
    if (agents.includes(currentAgentId)) {
      setAgentId(currentAgentId);
    }
  }, [agents, currentAgentId]);

  const recentRuns = useMemo(() => runs.slice(0, 10), [runs]);
  const recentFailures = useMemo(() => failures.slice(0, 10), [failures]);
  const recentHeartbeat = useMemo(
    () => heartbeatRuns.slice(0, 10),
    [heartbeatRuns],
  );

  async function handleSubmitJob() {
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
      await refreshAll(agentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save cron job");
    }
  }

  return (
    <main
      id="main-content"
      className="app-main flex h-screen flex-col overflow-hidden"
    >
      <Navbar />
      <section className="flex h-full min-h-0 flex-col gap-3 p-3">
        <div className="panel-shell">
          <div className="ui-panel-header">
            <h1 className="ui-panel-title">Scheduler</h1>
            <div className="flex items-center gap-2">
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
                className="mt-1 ui-mono text-xs"
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
                className="mt-1 ui-mono text-xs"
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
                className="mt-1 ui-mono text-xs"
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
            </label>
            <label className="min-w-0 md:col-span-2">
              <span className="ui-label">Prompt</span>
              <Input
                className="mt-1 text-xs"
                value={draft.prompt}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, prompt: event.target.value }))
                }
                placeholder="Prompt executed when this cron job runs"
              />
            </label>
            <label className="min-w-0">
              <span className="ui-label">Name</span>
              <Input
                className="mt-1 text-xs"
                value={draft.name}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, name: event.target.value }))
                }
                placeholder="optional job name"
              />
            </label>
            <label className="flex items-center gap-2 pt-6 text-xs text-[var(--muted)]">
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
                className="px-3 text-xs"
                onClick={() => void handleSubmitJob()}
              >
                {draft.id ? "Update Job" : "Create Job"}
              </Button>
              {draft.id ? (
                <Button
                  type="button"
                  className="px-3 text-xs"
                  onClick={() => setDraft(EMPTY_DRAFT)}
                >
                  Cancel Edit
                </Button>
              ) : null}
            </div>
          </div>
          {error ? (
            <div className="px-4 pb-4 text-xs text-[var(--danger)]">
              {error}
            </div>
          ) : null}
        </div>

        <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-3">
          <div className="panel-shell min-h-0 lg:col-span-2">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Cron Jobs</h2>
              <Badge tone="neutral">{jobs.length} jobs</Badge>
            </div>
            <TableWrap className="m-3 mt-0 max-h-full">
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
                            className="min-h-[24px] px-2 text-[10px]"
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
                            className="min-h-[24px] px-2 text-[10px]"
                            onClick={async () => {
                              await runCronJob(job.id, agentId);
                              await refreshAll(agentId);
                            }}
                          >
                            Run now
                          </Button>
                          <Button
                            type="button"
                            variant="danger"
                            className="min-h-[24px] px-2 text-[10px]"
                            onClick={async () => {
                              await deleteCronJob(job.id, agentId);
                              await refreshAll(agentId);
                            }}
                          >
                            Delete
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {jobs.length === 0 ? (
                    <tr>
                      <td
                        colSpan={6}
                        className="text-center text-[var(--muted)]"
                      >
                        No cron jobs configured.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </DataTable>
            </TableWrap>
          </div>

          <div className="panel-shell min-h-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Heartbeat</h2>
              <Badge tone={heartbeat.enabled ? "success" : "warn"}>
                {heartbeat.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            <div className="space-y-2 p-4">
              <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
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
                  className="mt-1 ui-mono text-xs"
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
                  className="mt-1 ui-mono text-xs"
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
                  className="mt-1 ui-mono text-xs"
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
                  className="mt-1 ui-mono text-xs"
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
                  className="mt-1 ui-mono text-xs"
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
                className="w-full text-xs"
                onClick={async () => {
                  await updateHeartbeatConfig(heartbeat, agentId);
                  await refreshAll(agentId);
                }}
              >
                Save Heartbeat
              </Button>
            </div>
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-3">
          <div className="panel-shell min-h-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Recent Runs</h2>
              <Badge tone="neutral">{recentRuns.length}</Badge>
            </div>
            <TableWrap className="m-3 mt-0">
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
          </div>
          <div className="panel-shell min-h-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Recent Failures</h2>
              <Badge tone="warn">{recentFailures.length}</Badge>
            </div>
            <TableWrap className="m-3 mt-0">
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
          </div>
          <div className="panel-shell min-h-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Heartbeat Runs</h2>
              <Badge tone="neutral">{recentHeartbeat.length}</Badge>
            </div>
            <TableWrap className="m-3 mt-0">
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
          </div>
        </div>
      </section>
    </main>
  );
}
