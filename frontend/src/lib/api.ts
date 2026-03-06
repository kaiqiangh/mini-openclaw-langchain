const API_BASE_ENV = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
export const API_BASE = API_BASE_ENV.trim().replace(/\/$/, "");
const ADMIN_BOOTSTRAP_PATH = "/api/auth/session";
let adminBootstrapPromise: Promise<boolean> | null = null;

function withAuthHeaders(headers?: HeadersInit): Headers {
  return new Headers(headers ?? {});
}

function canBootstrapAdminSession(url: string): boolean {
  if (typeof window === "undefined" || process.env.NODE_ENV === "test") {
    return false;
  }
  try {
    const target = new URL(url, window.location.origin);
    return target.origin === window.location.origin;
  } catch {
    return false;
  }
}

async function bootstrapAdminSession(): Promise<boolean> {
  if (typeof window === "undefined" || process.env.NODE_ENV === "test") {
    return false;
  }
  if (adminBootstrapPromise) {
    return adminBootstrapPromise;
  }
  adminBootstrapPromise = fetch(ADMIN_BOOTSTRAP_PATH, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
  })
    .then((response) => response.ok)
    .catch(() => false);
  const bootstrapped = await adminBootstrapPromise;
  adminBootstrapPromise = null;
  return bootstrapped;
}

async function fetchWithAdminSession(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const buildInit = (): RequestInit => ({
    ...init,
    credentials: "include",
    headers: withAuthHeaders(init?.headers),
  });

  let response = await fetch(url, buildInit());
  if (response.status !== 401 || !canBootstrapAdminSession(url)) {
    return response;
  }
  const bootstrapped = await bootstrapAdminSession();
  if (!bootstrapped) {
    return response;
  }
  response = await fetch(url, buildInit());
  return response;
}

async function readResponsePayload(
  response: Response,
): Promise<{ text: string; payload: Record<string, unknown> | null }> {
  const text = await response.text();
  if (!text.trim()) {
    return { text, payload: null };
  }
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object") {
      return { text, payload: parsed as Record<string, unknown> };
    }
  } catch {
    // Non-JSON responses should still surface their raw text.
  }
  return { text, payload: null };
}

export type StreamEvent = {
  event: string;
  data: string;
};

export type AgentMeta = {
  agent_id: string;
  path: string;
  created_at: number;
  updated_at: number;
  active_sessions: number;
  archived_sessions: number;
};

export type SessionMeta = {
  session_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  archived?: boolean;
};

export type ChatHistoryResponse = {
  session_id: string;
  agent_id?: string;
  messages: Array<{
    role: "user" | "assistant";
    content: string;
    timestamp_ms?: number;
    tool_calls?: Array<{ tool: string; input?: unknown; output?: unknown }>;
    streaming?: boolean;
    run_id?: string;
  }>;
  compressed_context?: string;
};

export type SkillMeta = {
  name: string;
  description: string;
  location: string;
};

export type WorkspaceFileIndex = {
  agent_id: string;
  workspace_root: string;
  files: string[];
};

export type UsageRecord = {
  schema_version: number;
  timestamp_ms: number;
  agent_id: string;
  provider: string;
  run_id: string;
  session_id: string;
  trigger_type: string;
  model: string;
  model_source: string;
  usage_source: string;
  input_tokens: number;
  input_uncached_tokens: number;
  input_cache_read_tokens: number;
  input_cache_write_tokens_5m: number;
  input_cache_write_tokens_1h: number;
  input_cache_write_tokens_unknown: number;
  output_tokens: number;
  reasoning_tokens: number;
  tool_input_tokens: number;
  total_tokens: number;
  priced: boolean;
  cost_usd: number | null;
  pricing: {
    provider: string;
    model: string;
    model_key: string | null;
    priced: boolean;
    currency: string;
    source: string;
    catalog_version: string;
    long_context_applied: boolean;
    total_cost_usd: number | null;
    unpriced_reason: string | null;
    line_items: Array<{
      kind: string;
      tokens: number;
      rate_usd_per_1m: number | null;
      cost_usd: number | null;
    }>;
  };
};

export type UsageSummary = {
  totals: {
    runs: number;
    priced_runs: number;
    unpriced_runs: number;
    input_tokens: number;
    input_uncached_tokens: number;
    input_cache_read_tokens: number;
    input_cache_write_tokens_5m: number;
    input_cache_write_tokens_1h: number;
    input_cache_write_tokens_unknown: number;
    output_tokens: number;
    reasoning_tokens: number;
    tool_input_tokens: number;
    total_tokens: number;
    cost_usd: number;
  };
  by_provider_model: Array<{
    provider: string;
    model: string;
    runs: number;
    priced_runs: number;
    unpriced_runs: number;
    input_tokens: number;
    input_uncached_tokens: number;
    input_cache_read_tokens: number;
    input_cache_write_tokens_5m: number;
    input_cache_write_tokens_1h: number;
    input_cache_write_tokens_unknown: number;
    output_tokens: number;
    reasoning_tokens: number;
    tool_input_tokens: number;
    total_tokens: number;
    cost_usd: number;
  }>;
  by_provider: Array<{
    provider: string;
    runs: number;
    priced_runs: number;
    unpriced_runs: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cost_usd: number;
  }>;
  count: number;
};

export type RuntimeConfigPayload = Record<string, unknown>;

export type CronJob = {
  id: string;
  name: string;
  schedule_type: "at" | "every" | "cron";
  schedule: string;
  prompt: string;
  enabled: boolean;
  next_run_ts: number;
  created_at: number;
  updated_at: number;
  last_run_ts: number;
  last_success_ts: number;
  failure_count: number;
  last_error: string;
};

export type HeartbeatConfig = {
  enabled: boolean;
  interval_seconds: number;
  timezone: string;
  active_start_hour: number;
  active_end_hour: number;
  session_id: string;
};

export type SchedulerMetricsWindow =
  | "1h"
  | "4h"
  | "12h"
  | "24h"
  | "7d"
  | "30d";

export type SchedulerMetricsBucket = "1m" | "5m" | "15m" | "1h";

export type SchedulerMetrics = {
  agent_id: string;
  window: SchedulerMetricsWindow;
  since_ms: number;
  generated_at_ms: number;
  totals: {
    events: number;
    cron_events: number;
    heartbeat_events: number;
  };
  cron: {
    runs: number;
    ok: number;
    error: number;
    success_rate: number | null;
  };
  heartbeat: {
    runs: number;
    ok: number;
    error: number;
    skipped: number;
  };
  duration: {
    count: number;
    avg_ms: number | null;
    min_ms: number | null;
    max_ms: number | null;
    p50_ms: number | null;
    p90_ms: number | null;
    p99_ms: number | null;
  };
  latency: {
    count: number;
    avg_ms: number | null;
    min_ms: number | null;
    max_ms: number | null;
    p50_ms: number | null;
    p90_ms: number | null;
    p99_ms: number | null;
  };
  status_breakdown: Record<string, number>;
};

export type SchedulerMetricsSeriesPoint = {
  ts_ms: number;
  label: string;
  total: number;
  cron_runs: number;
  cron_failures: number;
  heartbeat_runs: number;
  heartbeat_ok: number;
  heartbeat_error: number;
  heartbeat_skipped: number;
  avg_duration_ms: number | null;
  avg_latency_ms: number | null;
};

export type SchedulerMetricsSeries = {
  agent_id: string;
  window: SchedulerMetricsWindow;
  bucket: SchedulerMetricsBucket;
  since_ms: number;
  generated_at_ms: number;
  points: SchedulerMetricsSeriesPoint[];
};

export type AgentTemplateMeta = {
  name: string;
  description: string;
  path: string;
  updated_at: number;
};

export type AgentTemplateDetail = AgentTemplateMeta & {
  runtime_config: RuntimeConfigPayload;
};

export type AgentBulkDeleteResult = {
  requested_count: number;
  deleted_count: number;
  results: Array<{
    agent_id: string;
    deleted: boolean;
    error?: string;
  }>;
};

export type AgentBulkExportResult = {
  format: "json";
  generated_at_ms: number;
  agents: Array<{
    agent_id: string;
    metadata: AgentMeta;
    runtime_config: RuntimeConfigPayload;
  }>;
  errors: Array<{ agent_id: string; error: string }>;
};

export type AgentBulkRuntimePatchResult = {
  requested_count: number;
  updated_count: number;
  results: Array<{
    agent_id: string;
    updated: boolean;
    config?: RuntimeConfigPayload;
    error?: string;
  }>;
};

export type AgentRuntimeDiff = {
  agent_id: string;
  baseline: string;
  summary: {
    added: number;
    removed: number;
    changed: number;
    total: number;
  };
  added: Record<string, unknown>;
  removed: Record<string, unknown>;
  changed: Record<string, { from: unknown; to: unknown }>;
};

export type ToolSelectionTrigger = "chat" | "heartbeat" | "cron";

export type AgentToolTriggerStatus = {
  enabled: boolean;
  explicitly_enabled: boolean;
  explicitly_blocked?: boolean;
  allowed_by_policy: boolean;
  reason: string;
};

export type AgentToolItem = {
  name: string;
  description: string;
  permission_level: string;
  trigger_status: Record<ToolSelectionTrigger, AgentToolTriggerStatus>;
};

export type AgentToolCatalog = {
  agent_id: string;
  triggers: ToolSelectionTrigger[];
  enabled_tools: Record<ToolSelectionTrigger, string[]>;
  explicit_enabled_tools?: Record<ToolSelectionTrigger, string[]>;
  explicit_blocked_tools?: Record<ToolSelectionTrigger, string[]>;
  tools: AgentToolItem[];
};

export type TracingConfig = {
  provider: "langsmith";
  config_key: "OBS_TRACING_ENABLED";
  enabled: boolean;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithAdminSession(url, init);
  const { text, payload } = await readResponsePayload(response);
  if (!response.ok) {
    const message =
      (payload?.error as { message?: string } | undefined)?.message ||
      text.trim() ||
      `Request failed (${response.status})`;
    throw new Error(
      message,
    );
  }
  if (!text) {
    return {} as T;
  }
  if (!payload) {
    throw new Error(`Expected JSON response from ${url}`);
  }
  return payload as T;
}

function agentBase(agentId = "default"): string {
  return `${API_BASE}/api/v1/agents/${encodeURIComponent(agentId)}`;
}

export async function getAgents(): Promise<AgentMeta[]> {
  const payload = await requestJson<{ data: AgentMeta[] }>(
    `${API_BASE}/api/v1/agents`,
  );
  return payload.data;
}

export async function createAgentWorkspace(
  agentId: string,
): Promise<AgentMeta> {
  const payload = await requestJson<{ data: AgentMeta }>(
    `${API_BASE}/api/v1/agents`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id: agentId }),
    },
  );
  return payload.data;
}

export async function deleteAgentWorkspace(agentId: string): Promise<void> {
  await requestJson<{ data: { deleted: boolean; agent_id: string } }>(
    `${API_BASE}/api/v1/agents/${encodeURIComponent(agentId)}`,
    {
      method: "DELETE",
    },
  );
}

export async function bulkDeleteAgentWorkspaces(
  agentIds: string[],
): Promise<AgentBulkDeleteResult> {
  const payload = await requestJson<{ data: AgentBulkDeleteResult }>(
    `${API_BASE}/api/v1/agents/bulk-delete`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_ids: agentIds }),
    },
  );
  return payload.data;
}

export async function bulkExportAgentWorkspaces(
  agentIds: string[],
): Promise<AgentBulkExportResult> {
  const payload = await requestJson<{ data: AgentBulkExportResult }>(
    `${API_BASE}/api/v1/agents/bulk-export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_ids: agentIds, format: "json" }),
    },
  );
  return payload.data;
}

export async function bulkPatchAgentRuntime(
  agentIds: string[],
  patch: RuntimeConfigPayload,
  mode: "merge" | "replace" = "merge",
): Promise<AgentBulkRuntimePatchResult> {
  const payload = await requestJson<{ data: AgentBulkRuntimePatchResult }>(
    `${API_BASE}/api/v1/agents/bulk-runtime-patch`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_ids: agentIds, patch, mode }),
    },
  );
  return payload.data;
}

export async function listAgentTemplates(): Promise<AgentTemplateMeta[]> {
  const payload = await requestJson<{ data: AgentTemplateMeta[] }>(
    `${API_BASE}/api/v1/agents/templates`,
  );
  return payload.data;
}

export async function getAgentTemplate(
  templateName: string,
): Promise<AgentTemplateDetail> {
  const payload = await requestJson<{ data: AgentTemplateDetail }>(
    `${API_BASE}/api/v1/agents/templates/${encodeURIComponent(templateName)}`,
  );
  return payload.data;
}

export async function getAgentRuntimeDiff(
  agentId: string,
  baseline: string,
): Promise<AgentRuntimeDiff> {
  const payload = await requestJson<{ data: AgentRuntimeDiff }>(
    `${agentBase(agentId)}/runtime-diff?baseline=${encodeURIComponent(baseline)}`,
  );
  return payload.data;
}

export async function getAgentTools(
  agentId = "default",
): Promise<AgentToolCatalog> {
  const payload = await requestJson<{ data: AgentToolCatalog }>(
    `${agentBase(agentId)}/tools`,
  );
  return payload.data;
}

export async function setAgentToolSelection(
  trigger: ToolSelectionTrigger,
  enabledTools: string[],
  agentId = "default",
): Promise<AgentToolCatalog> {
  const payload = await requestJson<{ data: AgentToolCatalog }>(
    `${agentBase(agentId)}/tools/selection`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trigger, enabled_tools: enabledTools }),
    },
  );
  return payload.data;
}

export async function getSessions(
  scope: "active" | "archived" | "all" = "active",
  agentId = "default",
): Promise<SessionMeta[]> {
  const payload = await requestJson<{ data: SessionMeta[] }>(
    `${agentBase(agentId)}/sessions?scope=${encodeURIComponent(scope)}`,
  );
  return payload.data;
}

export async function createSession(
  title?: string,
  agentId = "default",
): Promise<{ session_id: string; title: string }> {
  const payload = await requestJson<{
    data: { session_id: string; title: string };
  }>(`${agentBase(agentId)}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(title ? { title } : {}),
  });
  return payload.data;
}

export async function archiveSession(
  sessionId: string,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { archived: boolean; session_id: string } }>(
    `${agentBase(agentId)}/sessions/${sessionId}/archive`,
    { method: "POST" },
  );
}

export async function restoreSession(
  sessionId: string,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { restored: boolean; session_id: string } }>(
    `${agentBase(agentId)}/sessions/${sessionId}/restore`,
    { method: "POST" },
  );
}

export async function deleteSession(
  sessionId: string,
  archived = false,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { deleted: boolean; session_id: string } }>(
    `${agentBase(agentId)}/sessions/${sessionId}?archived=${archived ? "true" : "false"}`,
    { method: "DELETE" },
  );
}

export async function getSessionHistory(
  sessionId: string,
  archived = false,
  agentId = "default",
): Promise<ChatHistoryResponse> {
  const payload = await requestJson<{ data: ChatHistoryResponse }>(
    `${agentBase(agentId)}/sessions/${sessionId}/history?archived=${archived ? "true" : "false"}`,
  );
  return payload.data;
}

export async function generateSessionTitle(
  sessionId: string,
  agentId = "default",
): Promise<{ session_id: string; title: string }> {
  const payload = await requestJson<{
    data: { session_id: string; title: string };
  }>(
    `${agentBase(agentId)}/sessions/${encodeURIComponent(sessionId)}/generate-title`,
    {
      method: "POST",
    },
  );
  return payload.data;
}

export async function getUsageSummary(params: {
  sinceHours: number;
  provider?: string;
  model?: string;
  triggerType?: string;
  agentId?: string;
}): Promise<UsageSummary> {
  const agentId = params.agentId ?? "default";
  const qs = new URLSearchParams();
  qs.set("since_hours", String(params.sinceHours));
  if (params.provider) qs.set("provider", params.provider);
  if (params.model) qs.set("model", params.model);
  if (params.triggerType) qs.set("trigger_type", params.triggerType);
  const payload = await requestJson<{ data: UsageSummary }>(
    `${agentBase(agentId)}/usage/summary?${qs.toString()}`,
  );
  return payload.data;
}

export async function getUsageRecords(params: {
  sinceHours: number;
  provider?: string;
  model?: string;
  triggerType?: string;
  limit?: number;
  agentId?: string;
}): Promise<UsageRecord[]> {
  const agentId = params.agentId ?? "default";
  const qs = new URLSearchParams();
  qs.set("since_hours", String(params.sinceHours));
  if (params.provider) qs.set("provider", params.provider);
  if (params.model) qs.set("model", params.model);
  if (params.triggerType) qs.set("trigger_type", params.triggerType);
  if (params.limit) qs.set("limit", String(params.limit));
  const payload = await requestJson<{ data: { records: UsageRecord[] } }>(
    `${agentBase(agentId)}/usage/records?${qs.toString()}`,
  );
  return payload.data.records;
}

export async function getRagMode(agentId = "default"): Promise<boolean> {
  const payload = await requestJson<{ data: { enabled: boolean } }>(
    `${agentBase(agentId)}/config/rag-mode`,
  );
  return payload.data.enabled;
}

export async function setRagMode(
  enabled: boolean,
  agentId = "default",
): Promise<boolean> {
  const payload = await requestJson<{ data: { enabled: boolean } }>(
    `${agentBase(agentId)}/config/rag-mode`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
  return payload.data.enabled;
}

export async function readWorkspaceFile(
  path: string,
  agentId = "default",
): Promise<string> {
  const payload = await requestJson<{
    data: { path: string; content: string };
  }>(
    `${agentBase(agentId)}/files?path=${encodeURIComponent(path)}`,
  );
  return payload.data.content;
}

export async function saveWorkspaceFile(
  path: string,
  content: string,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { saved: boolean } }>(
    `${agentBase(agentId)}/files`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content }),
    },
  );
}

export async function listSkills(): Promise<SkillMeta[]> {
  const payload = await requestJson<{ data: SkillMeta[] }>(
    `${API_BASE}/api/v1/skills`,
  );
  return payload.data;
}

export async function listAgentSkills(
  agentId = "default",
): Promise<SkillMeta[]> {
  const payload = await requestJson<{ data: SkillMeta[] }>(
    `${agentBase(agentId)}/skills`,
  );
  return payload.data;
}

export async function listWorkspaceFiles(
  agentId = "default",
): Promise<WorkspaceFileIndex> {
  const payload = await requestJson<{ data: WorkspaceFileIndex }>(
    `${agentBase(agentId)}/files/index`,
  );
  return payload.data;
}

export async function getRuntimeConfig(
  agentId = "default",
): Promise<RuntimeConfigPayload> {
  const payload = await requestJson<{ data: { config: RuntimeConfigPayload } }>(
    `${agentBase(agentId)}/config/runtime`,
  );
  return payload.data.config;
}

export async function setRuntimeConfig(
  config: RuntimeConfigPayload,
  agentId = "default",
): Promise<RuntimeConfigPayload> {
  const payload = await requestJson<{ data: { config: RuntimeConfigPayload } }>(
    `${agentBase(agentId)}/config/runtime`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    },
  );
  return payload.data.config;
}

export async function getTracingConfig(): Promise<TracingConfig> {
  const payload = await requestJson<{ data: TracingConfig }>(
    `${API_BASE}/api/v1/config/tracing`,
  );
  return payload.data;
}

export async function setTracingConfig(
  enabled: boolean,
): Promise<TracingConfig> {
  const payload = await requestJson<{ data: TracingConfig }>(
    `${API_BASE}/api/v1/config/tracing`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
  return payload.data;
}

export async function listCronJobs(agentId = "default"): Promise<CronJob[]> {
  const payload = await requestJson<{ data: { jobs: CronJob[] } }>(
    `${agentBase(agentId)}/scheduler/cron/jobs`,
  );
  return payload.data.jobs;
}

export async function createCronJob(
  request: {
    name: string;
    schedule_type: "at" | "every" | "cron";
    schedule: string;
    prompt: string;
    enabled?: boolean;
  },
  agentId = "default",
): Promise<CronJob> {
  const payload = await requestJson<{ data: { job: CronJob } }>(
    `${agentBase(agentId)}/scheduler/cron/jobs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return payload.data.job;
}

export async function updateCronJob(
  jobId: string,
  request: Partial<{
    name: string;
    schedule_type: "at" | "every" | "cron";
    schedule: string;
    prompt: string;
    enabled: boolean;
  }>,
  agentId = "default",
): Promise<CronJob> {
  const payload = await requestJson<{ data: { job: CronJob } }>(
    `${agentBase(agentId)}/scheduler/cron/jobs/${encodeURIComponent(jobId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return payload.data.job;
}

export async function deleteCronJob(
  jobId: string,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { deleted: boolean } }>(
    `${agentBase(agentId)}/scheduler/cron/jobs/${encodeURIComponent(jobId)}`,
    { method: "DELETE" },
  );
}

export async function runCronJob(
  jobId: string,
  agentId = "default",
): Promise<CronJob> {
  const payload = await requestJson<{ data: { job: CronJob } }>(
    `${agentBase(agentId)}/scheduler/cron/jobs/${encodeURIComponent(jobId)}/run`,
    { method: "POST" },
  );
  return payload.data.job;
}

export async function listCronRuns(
  agentId = "default",
  limit = 100,
): Promise<Array<Record<string, unknown>>> {
  const payload = await requestJson<{
    data: { runs: Array<Record<string, unknown>> };
  }>(`${agentBase(agentId)}/scheduler/cron/runs?limit=${limit}`);
  return payload.data.runs;
}

export async function listCronFailures(
  agentId = "default",
  limit = 100,
): Promise<Array<Record<string, unknown>>> {
  const payload = await requestJson<{
    data: { failures: Array<Record<string, unknown>> };
  }>(`${agentBase(agentId)}/scheduler/cron/failures?limit=${limit}`);
  return payload.data.failures;
}

export async function getHeartbeatConfig(
  agentId = "default",
): Promise<HeartbeatConfig> {
  const payload = await requestJson<{ data: { config: HeartbeatConfig } }>(
    `${agentBase(agentId)}/scheduler/heartbeat`,
  );
  return payload.data.config;
}

export async function updateHeartbeatConfig(
  request: Partial<HeartbeatConfig>,
  agentId = "default",
): Promise<HeartbeatConfig> {
  const payload = await requestJson<{ data: { config: HeartbeatConfig } }>(
    `${agentBase(agentId)}/scheduler/heartbeat`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return payload.data.config;
}

export async function listHeartbeatRuns(
  agentId = "default",
  limit = 100,
): Promise<Array<Record<string, unknown>>> {
  const payload = await requestJson<{
    data: { runs: Array<Record<string, unknown>> };
  }>(`${agentBase(agentId)}/scheduler/heartbeat/runs?limit=${limit}`);
  return payload.data.runs;
}

export async function getSchedulerMetrics(
  agentId = "default",
  window: SchedulerMetricsWindow = "24h",
): Promise<SchedulerMetrics> {
  const payload = await requestJson<{ data: SchedulerMetrics }>(
    `${agentBase(agentId)}/scheduler/metrics?window=${encodeURIComponent(window)}`,
  );
  return payload.data;
}

export async function getSchedulerMetricsTimeseries(
  agentId = "default",
  window: SchedulerMetricsWindow = "24h",
  bucket: SchedulerMetricsBucket = "5m",
): Promise<SchedulerMetricsSeries> {
  const payload = await requestJson<{ data: SchedulerMetricsSeries }>(
    `${agentBase(agentId)}/scheduler/metrics/timeseries?window=${encodeURIComponent(window)}&bucket=${encodeURIComponent(bucket)}`,
  );
  return payload.data;
}

export async function streamChat(
  message: string,
  sessionId: string,
  onEvent: (event: StreamEvent) => void,
  agentId = "default",
  resumeSameTurn = false,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetchWithAdminSession(`${agentBase(agentId)}/chat`, {
    method: "POST",
    signal,
    headers: withAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      message,
      session_id: sessionId,
      stream: true,
      resume_same_turn: resumeSameTurn,
    }),
  });

  if (!response.ok) {
    const { text, payload } = await readResponsePayload(response);
    const detail =
      (payload?.error as { message?: string } | undefined)?.message ||
      text.trim() ||
      "SSE stream request failed";
    throw new Error(
      detail,
    );
  }

  if (!response.body) {
    throw new Error("SSE stream is unavailable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const emitChunk = (chunk: string) => {
    if (!chunk.trim()) return;
    const lines = chunk.split("\n");
    let event = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith("event:")) {
        event = line.replace("event:", "").trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.replace("data:", "").trim());
      }
    }

    onEvent({
      event,
      data: dataLines.join("\n"),
    });
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      emitChunk(chunk);
    }
  }

  emitChunk(buffer);
}
