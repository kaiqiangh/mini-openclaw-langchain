import { UsageRecord } from "@/lib/api";

export type RunWindow = "1h" | "4h" | "12h" | "24h" | "7d" | "30d";
export type RunTriggerFilter = "all" | "chat" | "cron" | "heartbeat";
export type RunTriggerType = "chat" | "cron" | "heartbeat" | "other";
export type RunSource = "usage" | "cron" | "heartbeat";

export type RunLedgerRow = {
  rowId: string;
  source: RunSource;
  triggerType: RunTriggerType;
  timestampMs: number;
  status: string;
  runId: string | null;
  sessionId: string | null;
  jobId: string | null;
  label: string;
  durationMs: number | null;
  totalTokens: number | null;
  costUsd: number | null;
  errorSummary: string;
  provider: string | null;
  model: string | null;
  raw: Record<string, unknown>;
};

const WINDOW_TO_HOURS: Record<RunWindow, number> = {
  "1h": 1,
  "4h": 4,
  "12h": 12,
  "24h": 24,
  "7d": 24 * 7,
  "30d": 24 * 30,
};
const SESSION_USAGE_MATCH_MAX_DISTANCE_MS = 5 * 60 * 1000;

function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asNumber(value: unknown): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return parsed;
}

function normalizeTriggerType(value: unknown): RunTriggerType {
  const normalized = asText(value).toLowerCase();
  if (normalized === "chat") return "chat";
  if (normalized === "cron") return "cron";
  if (normalized === "heartbeat") return "heartbeat";
  return "other";
}

function buildRowId(parts: Array<string | number | null | undefined>): string {
  return parts
    .map((part) => String(part ?? "").trim())
    .filter(Boolean)
    .join(":");
}

function pickTimestamp(row: Record<string, unknown>): number {
  return (
    asNumber(row.finished_at_ms) ??
    asNumber(row.timestamp_ms) ??
    asNumber(row.started_at_ms) ??
    0
  );
}

function isSchedulerUsageRow(row: RunLedgerRow): boolean {
  return row.triggerType === "cron" || row.triggerType === "heartbeat";
}

function indexUsageRows(rows: RunLedgerRow[]) {
  const byRunId = new Map<string, RunLedgerRow>();
  const bySessionId = new Map<string, RunLedgerRow[]>();

  for (const row of rows) {
    if (!isSchedulerUsageRow(row)) {
      continue;
    }
    if (row.runId) {
      byRunId.set(row.runId, row);
    }
    if (row.sessionId) {
      const existing = bySessionId.get(row.sessionId) ?? [];
      existing.push(row);
      bySessionId.set(row.sessionId, existing);
    }
  }

  return { byRunId, bySessionId };
}

function matchSchedulerUsage(
  row: RunLedgerRow,
  indexes: ReturnType<typeof indexUsageRows>,
  consumedUsageRowIds: Set<string>,
): RunLedgerRow | null {
  if (row.runId) {
    const match = indexes.byRunId.get(row.runId);
    if (
      match &&
      match.triggerType === row.triggerType &&
      !consumedUsageRowIds.has(match.rowId)
    ) {
      return match;
    }
  }

  if (!row.sessionId) {
    return null;
  }

  const candidates = indexes.bySessionId.get(row.sessionId) ?? [];
  let bestMatch: RunLedgerRow | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const candidate of candidates) {
    if (candidate.triggerType !== row.triggerType) {
      continue;
    }
    if (consumedUsageRowIds.has(candidate.rowId)) {
      continue;
    }
    const distance = Math.abs(candidate.timestampMs - row.timestampMs);
    if (distance < bestDistance) {
      bestMatch = candidate;
      bestDistance = distance;
    }
  }

  if (bestDistance > SESSION_USAGE_MATCH_MAX_DISTANCE_MS) {
    return null;
  }
  return bestMatch;
}

function enrichSchedulerRow(
  row: RunLedgerRow,
  indexes: ReturnType<typeof indexUsageRows>,
  consumedUsageRowIds: Set<string>,
): RunLedgerRow {
  const usageRow = matchSchedulerUsage(row, indexes, consumedUsageRowIds);
  if (!usageRow) {
    return row;
  }

  consumedUsageRowIds.add(usageRow.rowId);
  return {
    ...row,
    runId: row.runId ?? usageRow.runId,
    sessionId: row.sessionId ?? usageRow.sessionId,
    totalTokens: usageRow.totalTokens,
    costUsd: usageRow.costUsd,
    provider: usageRow.provider,
    model: usageRow.model,
    raw: {
      ...row.raw,
      usage: usageRow.raw,
    },
  };
}

export function normalizeRunWindow(value: string | null | undefined): RunWindow {
  if (value === "1h" || value === "4h" || value === "12h" || value === "24h") {
    return value;
  }
  if (value === "7d" || value === "30d") {
    return value;
  }
  return "24h";
}

export function normalizeRunTriggerFilter(
  value: string | null | undefined,
): RunTriggerFilter {
  if (value === "chat" || value === "cron" || value === "heartbeat") {
    return value;
  }
  return "all";
}

export function windowToHours(window: RunWindow): number {
  return WINDOW_TO_HOURS[window];
}

export function getRunWindowStart(
  window: RunWindow,
  nowMs = Date.now(),
): number {
  return nowMs - windowToHours(window) * 60 * 60 * 1000;
}

export function normalizeUsageRun(row: UsageRecord): RunLedgerRow {
  const triggerType = normalizeTriggerType(row.trigger_type);
  const runId = asText(row.run_id) || null;
  const sessionId = asText(row.session_id) || null;

  return {
    rowId: buildRowId([
      "usage",
      runId ?? sessionId ?? row.timestamp_ms,
      row.timestamp_ms,
    ]),
    source: "usage",
    triggerType,
    timestampMs: row.timestamp_ms,
    status: "recorded",
    runId,
    sessionId,
    jobId: null,
    label: runId ?? sessionId ?? row.model ?? "usage-record",
    durationMs: null,
    totalTokens: row.total_tokens,
    costUsd: row.cost_usd,
    errorSummary: "",
    provider: row.provider || null,
    model: row.model || null,
    raw: row as unknown as Record<string, unknown>,
  };
}

export function normalizeCronRun(row: Record<string, unknown>): RunLedgerRow {
  const timestampMs = pickTimestamp(row);
  const jobId = asText(row.job_id) || null;
  const sessionId = asText(row.session_id) || (jobId ? `__cron__:${jobId}` : null);
  const label = asText(row.name) || jobId || "cron-job";

  return {
    rowId: buildRowId([
      "cron",
      jobId ?? label,
      timestampMs,
      asText(row.status) || "ok",
    ]),
    source: "cron",
    triggerType: "cron",
    timestampMs,
    status: asText(row.status) || "ok",
    runId: asText(row.run_id) || null,
    sessionId,
    jobId,
    label,
    durationMs: asNumber(row.duration_ms),
    totalTokens: null,
    costUsd: null,
    errorSummary: asText(row.error),
    provider: null,
    model: null,
    raw: row,
  };
}

export function normalizeHeartbeatRun(
  row: Record<string, unknown>,
): RunLedgerRow {
  const timestampMs = pickTimestamp(row);
  const details =
    row.details && typeof row.details === "object"
      ? (row.details as Record<string, unknown>)
      : {};
  const runId = asText(row.run_id) || asText(details.run_id) || null;
  const sessionId = asText(details.session_id) || null;
  const errorSummary =
    asText(details.error) || asText(details.response_preview) || "";

  return {
    rowId: buildRowId([
      "heartbeat",
      sessionId ?? "heartbeat",
      timestampMs,
      asText(row.status) || "unknown",
    ]),
    source: "heartbeat",
    triggerType: "heartbeat",
    timestampMs,
    status: asText(row.status) || "unknown",
    runId,
    sessionId,
    jobId: null,
    label: sessionId ?? "heartbeat",
    durationMs: asNumber(row.duration_ms),
    totalTokens: null,
    costUsd: null,
    errorSummary,
    provider: null,
    model: null,
    raw: row,
  };
}

export function buildRunLedgerRows(input: {
  usageRecords: UsageRecord[];
  cronRuns: Array<Record<string, unknown>>;
  cronFailures?: Array<Record<string, unknown>>;
  heartbeatRuns: Array<Record<string, unknown>>;
}): RunLedgerRow[] {
  const rows: RunLedgerRow[] = [];
  const normalizedUsageRows = input.usageRecords.map((record) =>
    normalizeUsageRun(record),
  );
  const schedulerUsageIndexes = indexUsageRows(normalizedUsageRows);
  const consumedSchedulerUsageRowIds = new Set<string>();

  for (const normalized of normalizedUsageRows) {
    if (isSchedulerUsageRow(normalized)) {
      continue;
    }
    rows.push(normalized);
  }

  for (const row of input.cronRuns) {
    rows.push(
      enrichSchedulerRow(
        normalizeCronRun(row),
        schedulerUsageIndexes,
        consumedSchedulerUsageRowIds,
      ),
    );
  }

  for (const row of input.cronFailures ?? []) {
    rows.push(
      enrichSchedulerRow(
        normalizeCronRun(row),
        schedulerUsageIndexes,
        consumedSchedulerUsageRowIds,
      ),
    );
  }

  for (const row of input.heartbeatRuns) {
    rows.push(
      enrichSchedulerRow(
        normalizeHeartbeatRun(row),
        schedulerUsageIndexes,
        consumedSchedulerUsageRowIds,
      ),
    );
  }

  return rows.sort((left, right) => {
    if (right.timestampMs !== left.timestampMs) {
      return right.timestampMs - left.timestampMs;
    }
    return left.rowId.localeCompare(right.rowId);
  });
}

export function filterRunLedgerRows(
  rows: RunLedgerRow[],
  trigger: RunTriggerFilter,
  options?: {
    minimumTimestampMs?: number;
  },
): RunLedgerRow[] {
  return rows.filter((row) => {
    if (
      typeof options?.minimumTimestampMs === "number" &&
      row.timestampMs < options.minimumTimestampMs
    ) {
      return false;
    }

    if (trigger === "all") {
      return true;
    }

    return row.triggerType === trigger;
  });
}

export function formatRunMetric(
  value: number | string | null | undefined,
): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}
