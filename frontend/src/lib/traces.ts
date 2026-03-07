import { TraceEventRecord } from "@/lib/api";

export type TraceWindow = "1h" | "4h" | "12h" | "24h" | "7d" | "30d";
export type TraceEventFilter =
  | "all"
  | "tool_start"
  | "tool_end"
  | "llm_start"
  | "llm_end"
  | "llm_error"
  | "error"
  | "unknown";
export type TraceTriggerFilter =
  | "all"
  | "chat"
  | "cron"
  | "heartbeat"
  | "unknown";

const TRACE_WINDOWS = new Set<TraceWindow>(["1h", "4h", "12h", "24h", "7d", "30d"]);
const TRACE_EVENTS = new Set<TraceEventFilter>([
  "all",
  "tool_start",
  "tool_end",
  "llm_start",
  "llm_end",
  "llm_error",
  "error",
  "unknown",
]);
const TRACE_TRIGGERS = new Set<TraceTriggerFilter>([
  "all",
  "chat",
  "cron",
  "heartbeat",
  "unknown",
]);

export function normalizeTraceWindow(value: string | null | undefined): TraceWindow {
  if (value && TRACE_WINDOWS.has(value as TraceWindow)) {
    return value as TraceWindow;
  }
  return "24h";
}

export function normalizeTraceEventFilter(
  value: string | null | undefined,
): TraceEventFilter {
  if (value && TRACE_EVENTS.has(value as TraceEventFilter)) {
    return value as TraceEventFilter;
  }
  return "all";
}

export function normalizeTraceTriggerFilter(
  value: string | null | undefined,
): TraceTriggerFilter {
  if (value && TRACE_TRIGGERS.has(value as TraceTriggerFilter)) {
    return value as TraceTriggerFilter;
  }
  return "all";
}

export function formatTraceTimestamp(timestampMs: number): string {
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) return "—";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestampMs));
}

export function traceSummaryEntries(summary: Record<string, number>) {
  return Object.entries(summary).sort(([left], [right]) => left.localeCompare(right));
}

export function traceFilterMatchesSelection(
  event: TraceEventRecord,
  traceId: string,
): boolean {
  return event.event_id === traceId;
}
