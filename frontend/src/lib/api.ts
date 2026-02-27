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
  timestamp_ms: number;
  run_id: string;
  session_id: string;
  trigger_type: string;
  model: string;
  input_tokens: number;
  cached_input_tokens: number;
  uncached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  source?: string;
};

export type UsageSummary = {
  totals: {
    runs: number;
    input_tokens: number;
    cached_input_tokens: number;
    uncached_input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    total_tokens: number;
    estimated_cost_usd: number;
  };
  by_model: Array<{
    model: string;
    runs: number;
    input_tokens: number;
    cached_input_tokens: number;
    uncached_input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    total_tokens: number;
    estimated_cost_usd: number;
  }>;
  count: number;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error?.message ?? `Request failed (${response.status})`);
  }
  return payload as T;
}

function withAgent(path: string, agentId = "default"): string {
  const hasQuery = path.includes("?");
  const suffix = `agent_id=${encodeURIComponent(agentId)}`;
  return `${path}${hasQuery ? "&" : "?"}${suffix}`;
}

export async function getAgents(): Promise<AgentMeta[]> {
  const payload = await requestJson<{ data: AgentMeta[] }>(`${API_BASE}/api/agents`);
  return payload.data;
}

export async function createAgentWorkspace(agentId: string): Promise<AgentMeta> {
  const payload = await requestJson<{ data: AgentMeta }>(`${API_BASE}/api/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId }),
  });
  return payload.data;
}

export async function deleteAgentWorkspace(agentId: string): Promise<void> {
  await requestJson<{ data: { deleted: boolean; agent_id: string } }>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });
}

export async function getSessions(
  scope: "active" | "archived" | "all" = "active",
  agentId = "default",
): Promise<SessionMeta[]> {
  const payload = await requestJson<{ data: SessionMeta[] }>(
    withAgent(`${API_BASE}/api/sessions?scope=${encodeURIComponent(scope)}`, agentId),
  );
  return payload.data;
}

export async function createSession(
  title?: string,
  agentId = "default",
): Promise<{ session_id: string; title: string }> {
  const payload = await requestJson<{ data: { session_id: string; title: string } }>(
    withAgent(`${API_BASE}/api/sessions`, agentId),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(title ? { title } : {}),
    },
  );
  return payload.data;
}

export async function archiveSession(sessionId: string, agentId = "default"): Promise<void> {
  await requestJson<{ data: { archived: boolean; session_id: string } }>(
    withAgent(`${API_BASE}/api/sessions/${sessionId}/archive`, agentId),
    { method: "POST" },
  );
}

export async function restoreSession(sessionId: string, agentId = "default"): Promise<void> {
  await requestJson<{ data: { restored: boolean; session_id: string } }>(
    withAgent(`${API_BASE}/api/sessions/${sessionId}/restore`, agentId),
    { method: "POST" },
  );
}

export async function deleteSession(sessionId: string, archived = false, agentId = "default"): Promise<void> {
  await requestJson<{ data: { deleted: boolean; session_id: string } }>(
    withAgent(`${API_BASE}/api/sessions/${sessionId}?archived=${archived ? "true" : "false"}`, agentId),
    { method: "DELETE" },
  );
}

export async function getSessionHistory(
  sessionId: string,
  archived = false,
  agentId = "default",
): Promise<ChatHistoryResponse> {
  const payload = await requestJson<{ data: ChatHistoryResponse }>(
    withAgent(`${API_BASE}/api/sessions/${sessionId}/history?archived=${archived ? "true" : "false"}`, agentId),
  );
  return payload.data;
}

export async function getUsageSummary(params: {
  sinceHours: number;
  model?: string;
  triggerType?: string;
  agentId?: string;
}): Promise<UsageSummary> {
  const qs = new URLSearchParams();
  qs.set("since_hours", String(params.sinceHours));
  if (params.model) qs.set("model", params.model);
  if (params.triggerType) qs.set("trigger_type", params.triggerType);
  qs.set("agent_id", params.agentId ?? "default");
  const payload = await requestJson<{ data: UsageSummary }>(`${API_BASE}/api/usage/summary?${qs.toString()}`);
  return payload.data;
}

export async function getUsageRecords(params: {
  sinceHours: number;
  model?: string;
  triggerType?: string;
  limit?: number;
  agentId?: string;
}): Promise<UsageRecord[]> {
  const qs = new URLSearchParams();
  qs.set("since_hours", String(params.sinceHours));
  if (params.model) qs.set("model", params.model);
  if (params.triggerType) qs.set("trigger_type", params.triggerType);
  if (params.limit) qs.set("limit", String(params.limit));
  qs.set("agent_id", params.agentId ?? "default");
  const payload = await requestJson<{ data: { records: UsageRecord[] } }>(
    `${API_BASE}/api/usage/records?${qs.toString()}`,
  );
  return payload.data.records;
}

export async function getRagMode(): Promise<boolean> {
  const payload = await requestJson<{ data: { enabled: boolean } }>(`${API_BASE}/api/config/rag-mode`);
  return payload.data.enabled;
}

export async function setRagMode(enabled: boolean): Promise<boolean> {
  const payload = await requestJson<{ data: { enabled: boolean } }>(`${API_BASE}/api/config/rag-mode`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return payload.data.enabled;
}

export async function readWorkspaceFile(path: string, agentId = "default"): Promise<string> {
  const payload = await requestJson<{ data: { path: string; content: string } }>(
    withAgent(`${API_BASE}/api/files?path=${encodeURIComponent(path)}`, agentId),
  );
  return payload.data.content;
}

export async function saveWorkspaceFile(path: string, content: string, agentId = "default"): Promise<void> {
  await requestJson<{ data: { saved: boolean } }>(withAgent(`${API_BASE}/api/files`, agentId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
}

export async function listSkills(): Promise<SkillMeta[]> {
  const payload = await requestJson<{ data: SkillMeta[] }>(`${API_BASE}/api/skills`);
  return payload.data;
}

export async function listWorkspaceFiles(agentId = "default"): Promise<WorkspaceFileIndex> {
  const payload = await requestJson<{ data: WorkspaceFileIndex }>(
    withAgent(`${API_BASE}/api/files/index`, agentId),
  );
  return payload.data;
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
    body: JSON.stringify({ message, session_id: sessionId, agent_id: agentId, stream: true }),
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
