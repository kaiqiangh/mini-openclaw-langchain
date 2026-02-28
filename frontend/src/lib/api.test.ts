import {
  getRagMode,
  getTracingConfig,
  setRagMode,
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
  it("appends agent_id to rag mode endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: { enabled: false } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: { enabled: true } }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await getRagMode("alpha");
    await setRagMode(true, "alpha");

    const firstUrl = String(fetchMock.mock.calls[0][0]);
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(firstUrl).toContain("agent_id=alpha");
    expect(secondUrl).toContain("agent_id=alpha");
  });
});

describe("tracing config requests", () => {
  it("calls global tracing endpoints without agent_id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            provider: "langsmith",
            config_key: "OBS_TRACING_ENABLED",
            enabled: false,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
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
    expect(firstUrl).toContain("/api/config/tracing");
    expect(secondUrl).toContain("/api/config/tracing");
    expect(firstUrl).not.toContain("agent_id=");
    expect(secondUrl).not.toContain("agent_id=");
  });
});
