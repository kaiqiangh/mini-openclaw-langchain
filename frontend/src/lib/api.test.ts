import {
  bulkDeleteAgentWorkspaces,
  bulkExportAgentWorkspaces,
  bulkPatchAgentRuntime,
  getAgentTools,
  getAgentRuntimeDiff,
  getAgentTemplate,
  getSchedulerMetrics,
  getSchedulerMetricsTimeseries,
  listAgentTemplates,
  getRagMode,
  getTracingConfig,
  setRagMode,
  setAgentToolSelection,
  setTracingConfig,
  streamChat,
} from "@/lib/api";

function createStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("streamChat", () => {
  it("parses SSE event chunks in order", async () => {
    const sse = [
      "event: token\r\n",
      'data: {"content":"A"}\r\n\r\n',
      "event: done\r\n",
      'data: {"content":"AB"}',
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: createStream(sse),
      }),
    );

    const events: Array<{ event: string; data: string }> = [];
    await streamChat("hello", "session-1", (event) => events.push(event));

    expect(events).toEqual([
      { event: "token", data: '{"content":"A"}' },
      { event: "done", data: '{"content":"AB"}' },
    ]);
  });
});

describe("agent-scoped rag mode requests", () => {
  it("uses agent path segments for rag mode endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ data: { enabled: false } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ data: { enabled: true } }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await getRagMode("alpha");
    await setRagMode(true, "alpha");

    const firstUrl = String(fetchMock.mock.calls[0][0]);
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(firstUrl).toContain("/api/v1/agents/alpha/config/rag-mode");
    expect(secondUrl).toContain("/api/v1/agents/alpha/config/rag-mode");
    expect(firstUrl).not.toContain("agent_id=");
    expect(secondUrl).not.toContain("agent_id=");
  });
});

describe("tracing config requests", () => {
  it("calls global tracing endpoints without agent_id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              provider: "langsmith",
              config_key: "OBS_TRACING_ENABLED",
              enabled: false,
            },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              provider: "langsmith",
              config_key: "OBS_TRACING_ENABLED",
              enabled: true,
            },
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await getTracingConfig();
    await setTracingConfig(true);

    const firstUrl = String(fetchMock.mock.calls[0][0]);
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(firstUrl).toContain("/api/v1/config/tracing");
    expect(secondUrl).toContain("/api/v1/config/tracing");
    expect(firstUrl).not.toContain("agent_id=");
    expect(secondUrl).not.toContain("agent_id=");
  });
});

describe("scheduler metrics requests", () => {
  it("calls scheduler metrics and timeseries endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              agent_id: "default",
              window: "24h",
              since_ms: 0,
              generated_at_ms: 0,
              totals: { events: 0, cron_events: 0, heartbeat_events: 0 },
              cron: { runs: 0, ok: 0, error: 0, success_rate: null },
              heartbeat: { runs: 0, ok: 0, error: 0, skipped: 0 },
              duration: {
                count: 0,
                avg_ms: null,
                min_ms: null,
                max_ms: null,
                p50_ms: null,
                p90_ms: null,
                p99_ms: null,
              },
              latency: {
                count: 0,
                avg_ms: null,
                min_ms: null,
                max_ms: null,
                p50_ms: null,
                p90_ms: null,
                p99_ms: null,
              },
              status_breakdown: {},
            },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              agent_id: "default",
              window: "24h",
              bucket: "15m",
              since_ms: 0,
              generated_at_ms: 0,
              points: [],
            },
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await getSchedulerMetrics("default", "24h");
    await getSchedulerMetricsTimeseries("default", "24h", "15m");

    const firstUrl = String(fetchMock.mock.calls[0][0]);
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(firstUrl).toContain("/api/v1/agents/default/scheduler/metrics?window=24h");
    expect(secondUrl).toContain(
      "/api/v1/agents/default/scheduler/metrics/timeseries?window=24h&bucket=15m",
    );
  });
});

describe("agent bulk/template requests", () => {
  it("calls agent bulk actions and template/runtime diff endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: { requested_count: 1, deleted_count: 1, results: [] },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: { format: "json", generated_at_ms: 1, agents: [], errors: [] },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: { requested_count: 1, updated_count: 1, results: [] },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ data: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              name: "safe-local",
              description: "",
              path: "/tmp",
              updated_at: 0,
              runtime_config: {},
            },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              agent_id: "default",
              baseline: "default",
              summary: { added: 0, removed: 0, changed: 0, total: 0 },
              added: {},
              removed: {},
              changed: {},
            },
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await bulkDeleteAgentWorkspaces(["default"]);
    await bulkExportAgentWorkspaces(["default"]);
    await bulkPatchAgentRuntime(["default"], {}, "merge");
    await listAgentTemplates();
    await getAgentTemplate("safe-local");
    await getAgentRuntimeDiff("default", "default");

    const urls = fetchMock.mock.calls.map((item) => String(item[0]));
    expect(urls[0]).toContain("/api/v1/agents/bulk-delete");
    expect(urls[1]).toContain("/api/v1/agents/bulk-export");
    expect(urls[2]).toContain("/api/v1/agents/bulk-runtime-patch");
    expect(urls[3]).toContain("/api/v1/agents/templates");
    expect(urls[4]).toContain("/api/v1/agents/templates/safe-local");
    expect(urls[5]).toContain("/api/v1/agents/default/runtime-diff?baseline=default");
  });
});

describe("agent tools requests", () => {
  it("calls tool catalog and selection endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              agent_id: "default",
              triggers: ["chat", "heartbeat", "cron"],
              enabled_tools: {
                chat: [],
                heartbeat: [],
                cron: [],
              },
              tools: [],
            },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            data: {
              agent_id: "default",
              triggers: ["chat", "heartbeat", "cron"],
              enabled_tools: {
                chat: ["terminal"],
                heartbeat: [],
                cron: [],
              },
              tools: [],
            },
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await getAgentTools("default");
    await setAgentToolSelection("chat", ["terminal"], "default");

    const firstUrl = String(fetchMock.mock.calls[0][0]);
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(firstUrl).toContain("/api/v1/agents/default/tools");
    expect(secondUrl).toContain("/api/v1/agents/default/tools/selection");
  });
});
