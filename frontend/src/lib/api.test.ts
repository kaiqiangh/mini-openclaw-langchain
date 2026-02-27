import { streamChat } from "@/lib/api";

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
