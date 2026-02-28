export const API_BASE =
  typeof window === "undefined"
    ? "http://localhost:8002"
    : `http://${window.location.hostname}:8002`;

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
    tool_calls?: Array<{ tool: string; input?: unknown; output?: unknown }>;
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

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(
      payload?.error?.message ?? `Request failed (${response.status})`,
    );
  }
  return payload as T;
}

function withAgent(path: string, agentId = "default"): string {
  const hasQuery = path.includes("?");
  const suffix = `agent_id=${encodeURIComponent(agentId)}`;
  return `${path}${hasQuery ? "&" : "?"}${suffix}`;
}

export async function getAgents(): Promise<AgentMeta[]> {
  const payload = await requestJson<{ data: AgentMeta[] }>(
    `${API_BASE}/api/agents`,
  );
  return payload.data;
}

export async function createAgentWorkspace(
  agentId: string,
): Promise<AgentMeta> {
  const payload = await requestJson<{ data: AgentMeta }>(
    `${API_BASE}/api/agents`,
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
    `${API_BASE}/api/agents/${encodeURIComponent(agentId)}`,
    {
      method: "DELETE",
    },
  );
}

export async function getSessions(
  scope: "active" | "archived" | "all" = "active",
  agentId = "default",
): Promise<SessionMeta[]> {
  const payload = await requestJson<{ data: SessionMeta[] }>(
    withAgent(
      `${API_BASE}/api/sessions?scope=${encodeURIComponent(scope)}`,
      agentId,
    ),
  );
  return payload.data;
}

export async function createSession(
  title?: string,
  agentId = "default",
): Promise<{ session_id: string; title: string }> {
  const payload = await requestJson<{
    data: { session_id: string; title: string };
  }>(withAgent(`${API_BASE}/api/sessions`, agentId), {
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
    withAgent(`${API_BASE}/api/sessions/${sessionId}/archive`, agentId),
    { method: "POST" },
  );
}

export async function restoreSession(
  sessionId: string,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { restored: boolean; session_id: string } }>(
    withAgent(`${API_BASE}/api/sessions/${sessionId}/restore`, agentId),
    { method: "POST" },
  );
}

export async function deleteSession(
  sessionId: string,
  archived = false,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { deleted: boolean; session_id: string } }>(
    withAgent(
      `${API_BASE}/api/sessions/${sessionId}?archived=${archived ? "true" : "false"}`,
      agentId,
    ),
    { method: "DELETE" },
  );
}

export async function getSessionHistory(
  sessionId: string,
  archived = false,
  agentId = "default",
): Promise<ChatHistoryResponse> {
  const payload = await requestJson<{ data: ChatHistoryResponse }>(
    withAgent(
      `${API_BASE}/api/sessions/${sessionId}/history?archived=${archived ? "true" : "false"}`,
      agentId,
    ),
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
  const qs = new URLSearchParams();
  qs.set("since_hours", String(params.sinceHours));
  if (params.provider) qs.set("provider", params.provider);
  if (params.model) qs.set("model", params.model);
  if (params.triggerType) qs.set("trigger_type", params.triggerType);
  qs.set("agent_id", params.agentId ?? "default");
  const payload = await requestJson<{ data: UsageSummary }>(
    `${API_BASE}/api/usage/summary?${qs.toString()}`,
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
  const qs = new URLSearchParams();
  qs.set("since_hours", String(params.sinceHours));
  if (params.provider) qs.set("provider", params.provider);
  if (params.model) qs.set("model", params.model);
  if (params.triggerType) qs.set("trigger_type", params.triggerType);
  if (params.limit) qs.set("limit", String(params.limit));
  qs.set("agent_id", params.agentId ?? "default");
  const payload = await requestJson<{ data: { records: UsageRecord[] } }>(
    `${API_BASE}/api/usage/records?${qs.toString()}`,
  );
  return payload.data.records;
}

export async function getRagMode(agentId = "default"): Promise<boolean> {
  const payload = await requestJson<{ data: { enabled: boolean } }>(
    withAgent(`${API_BASE}/api/config/rag-mode`, agentId),
  );
  return payload.data.enabled;
}

export async function setRagMode(
  enabled: boolean,
  agentId = "default",
): Promise<boolean> {
  const payload = await requestJson<{ data: { enabled: boolean } }>(
    withAgent(`${API_BASE}/api/config/rag-mode`, agentId),
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
    withAgent(
      `${API_BASE}/api/files?path=${encodeURIComponent(path)}`,
      agentId,
    ),
  );
  return payload.data.content;
}

export async function saveWorkspaceFile(
  path: string,
  content: string,
  agentId = "default",
): Promise<void> {
  await requestJson<{ data: { saved: boolean } }>(
    withAgent(`${API_BASE}/api/files`, agentId),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content }),
    },
  );
}

export async function listSkills(): Promise<SkillMeta[]> {
  const payload = await requestJson<{ data: SkillMeta[] }>(
    `${API_BASE}/api/skills`,
  );
  return payload.data;
}

export async function listWorkspaceFiles(
  agentId = "default",
): Promise<WorkspaceFileIndex> {
  const payload = await requestJson<{ data: WorkspaceFileIndex }>(
    withAgent(`${API_BASE}/api/files/index`, agentId),
  );
  return payload.data;
}

export async function getRuntimeConfig(
  agentId = "default",
): Promise<RuntimeConfigPayload> {
  const payload = await requestJson<{ data: { config: RuntimeConfigPayload } }>(
    withAgent(`${API_BASE}/api/config/runtime`, agentId),
  );
  return payload.data.config;
}

export async function setRuntimeConfig(
  config: RuntimeConfigPayload,
  agentId = "default",
): Promise<RuntimeConfigPayload> {
  const payload = await requestJson<{ data: { config: RuntimeConfigPayload } }>(
    withAgent(`${API_BASE}/api/config/runtime`, agentId),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    },
  );
  return payload.data.config;
}

export async function listCronJobs(agentId = "default"): Promise<CronJob[]> {
  const payload = await requestJson<{ data: { jobs: CronJob[] } }>(
    withAgent(`${API_BASE}/api/scheduler/cron/jobs`, agentId),
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
    withAgent(`${API_BASE}/api/scheduler/cron/jobs`, agentId),
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
    withAgent(
      `${API_BASE}/api/scheduler/cron/jobs/${encodeURIComponent(jobId)}`,
      agentId,
    ),
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
    withAgent(
      `${API_BASE}/api/scheduler/cron/jobs/${encodeURIComponent(jobId)}`,
      agentId,
    ),
    { method: "DELETE" },
  );
}

export async function runCronJob(
  jobId: string,
  agentId = "default",
): Promise<CronJob> {
  const payload = await requestJson<{ data: { job: CronJob } }>(
    withAgent(
      `${API_BASE}/api/scheduler/cron/jobs/${encodeURIComponent(jobId)}/run`,
      agentId,
    ),
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
  }>(withAgent(`${API_BASE}/api/scheduler/cron/runs?limit=${limit}`, agentId));
  return payload.data.runs;
}

export async function listCronFailures(
  agentId = "default",
  limit = 100,
): Promise<Array<Record<string, unknown>>> {
  const payload = await requestJson<{
    data: { failures: Array<Record<string, unknown>> };
  }>(
    withAgent(
      `${API_BASE}/api/scheduler/cron/failures?limit=${limit}`,
      agentId,
    ),
  );
  return payload.data.failures;
}

export async function getHeartbeatConfig(
  agentId = "default",
): Promise<HeartbeatConfig> {
  const payload = await requestJson<{ data: { config: HeartbeatConfig } }>(
    withAgent(`${API_BASE}/api/scheduler/heartbeat`, agentId),
  );
  return payload.data.config;
}

export async function updateHeartbeatConfig(
  request: Partial<HeartbeatConfig>,
  agentId = "default",
): Promise<HeartbeatConfig> {
  const payload = await requestJson<{ data: { config: HeartbeatConfig } }>(
    withAgent(`${API_BASE}/api/scheduler/heartbeat`, agentId),
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
  }>(
    withAgent(
      `${API_BASE}/api/scheduler/heartbeat/runs?limit=${limit}`,
      agentId,
    ),
  );
  return payload.data.runs;
}

export async function streamChat(
  message: string,
  sessionId: string,
  onEvent: (event: StreamEvent) => void,
  agentId = "default",
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      agent_id: agentId,
      stream: true,
    }),
  });

  if (!response.ok) {
    let detail = "SSE stream request failed";
    try {
      const payload = await response.json();
      detail = payload?.error?.message ?? detail;
    } catch {
      // ignore JSON parse failure
    }
    throw new Error(detail);
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
