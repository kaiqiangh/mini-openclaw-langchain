import {
  buildRunLedgerRows,
  filterRunLedgerRows,
  getRunWindowStart,
  normalizeRunTriggerFilter,
  normalizeRunWindow,
  normalizeUsageRun,
  windowToHours,
} from "@/lib/runs";

describe("runs normalization", () => {
  it("keeps chat usage rows and drops duplicate scheduler-backed usage triggers", () => {
    const rows = buildRunLedgerRows({
      usageRecords: [
        {
          schema_version: 1,
          timestamp_ms: 10,
          agent_id: "default",
          provider: "openai",
          run_id: "run-chat",
          session_id: "session-chat",
          trigger_type: "chat",
          model: "gpt-5",
          model_source: "catalog",
          usage_source: "stream",
          input_tokens: 10,
          input_uncached_tokens: 10,
          input_cache_read_tokens: 0,
          input_cache_write_tokens_5m: 0,
          input_cache_write_tokens_1h: 0,
          input_cache_write_tokens_unknown: 0,
          output_tokens: 5,
          reasoning_tokens: 0,
          tool_input_tokens: 0,
          total_tokens: 15,
          priced: true,
          cost_usd: 0.25,
          pricing: {
            provider: "openai",
            model: "gpt-5",
            model_key: "gpt-5",
            priced: true,
            currency: "USD",
            source: "catalog",
            catalog_version: "test",
            long_context_applied: false,
            total_cost_usd: 0.25,
            unpriced_reason: null,
            line_items: [],
          },
        },
        {
          schema_version: 1,
          timestamp_ms: 20,
          agent_id: "default",
          provider: "openai",
          run_id: "run-cron-usage",
          session_id: "session-cron",
          trigger_type: "cron",
          model: "gpt-5",
          model_source: "catalog",
          usage_source: "stream",
          input_tokens: 1,
          input_uncached_tokens: 1,
          input_cache_read_tokens: 0,
          input_cache_write_tokens_5m: 0,
          input_cache_write_tokens_1h: 0,
          input_cache_write_tokens_unknown: 0,
          output_tokens: 1,
          reasoning_tokens: 0,
          tool_input_tokens: 0,
          total_tokens: 2,
          priced: true,
          cost_usd: 0.02,
          pricing: {
            provider: "openai",
            model: "gpt-5",
            model_key: "gpt-5",
            priced: true,
            currency: "USD",
            source: "catalog",
            catalog_version: "test",
            long_context_applied: false,
            total_cost_usd: 0.02,
            unpriced_reason: null,
            line_items: [],
          },
        },
      ],
      cronRuns: [
        {
          timestamp_ms: 30,
          job_id: "cron-1",
          name: "Digest",
          status: "ok",
          duration_ms: 120,
        },
      ],
      cronFailures: [
        {
          timestamp_ms: 40,
          job_id: "cron-2",
          name: "Digest failure",
          status: "error",
          error: "boom",
        },
      ],
      heartbeatRuns: [
        {
          timestamp_ms: 50,
          status: "ok",
          details: { session_id: "__heartbeat__", response_preview: "HEARTBEAT_OK" },
        },
      ],
    });

    expect(rows.map((row) => [row.source, row.status, row.label])).toEqual([
      ["heartbeat", "ok", "__heartbeat__"],
      ["cron", "error", "Digest failure"],
      ["cron", "ok", "Digest"],
      ["usage", "recorded", "run-chat"],
    ]);
  });

  it("normalizes usage rows with conservative status semantics", () => {
    const row = normalizeUsageRun({
      schema_version: 1,
      timestamp_ms: 100,
      agent_id: "default",
      provider: "anthropic",
      run_id: "run-1",
      session_id: "session-1",
      trigger_type: "chat",
      model: "claude",
      model_source: "catalog",
      usage_source: "stream",
      input_tokens: 10,
      input_uncached_tokens: 10,
      input_cache_read_tokens: 0,
      input_cache_write_tokens_5m: 0,
      input_cache_write_tokens_1h: 0,
      input_cache_write_tokens_unknown: 0,
      output_tokens: 4,
      reasoning_tokens: 1,
      tool_input_tokens: 0,
      total_tokens: 14,
      priced: false,
      cost_usd: null,
      pricing: {
        provider: "anthropic",
        model: "claude",
        model_key: "claude",
        priced: false,
        currency: "USD",
        source: "catalog",
        catalog_version: "test",
        long_context_applied: false,
        total_cost_usd: null,
        unpriced_reason: "test",
        line_items: [],
      },
    });

    expect(row.status).toBe("recorded");
    expect(row.runId).toBe("run-1");
    expect(row.sessionId).toBe("session-1");
    expect(row.totalTokens).toBe(14);
    expect(row.costUsd).toBeNull();
  });

  it("filters rows by trigger without mutating ordering", () => {
    const rows = [
      { rowId: "a", triggerType: "chat" },
      { rowId: "b", triggerType: "cron" },
      { rowId: "c", triggerType: "heartbeat" },
    ] as any;

    expect(filterRunLedgerRows(rows, "all").map((row) => row.rowId)).toEqual([
      "a",
      "b",
      "c",
    ]);
    expect(filterRunLedgerRows(rows, "cron").map((row) => row.rowId)).toEqual([
      "b",
    ]);
  });

  it("filters rows by time window across all sources", () => {
    const nowMs = 1_710_000_000_000;
    const rows = [
      {
        rowId: "recent-chat",
        triggerType: "chat",
        timestampMs: nowMs - 30 * 60 * 1000,
      },
      {
        rowId: "stale-cron",
        triggerType: "cron",
        timestampMs: nowMs - 3 * 60 * 60 * 1000,
      },
      {
        rowId: "recent-heartbeat",
        triggerType: "heartbeat",
        timestampMs: nowMs - 10 * 60 * 1000,
      },
    ] as any;

    expect(
      filterRunLedgerRows(rows, "all", {
        minimumTimestampMs: getRunWindowStart("1h", nowMs),
      }).map((row) => row.rowId),
    ).toEqual(["recent-chat", "recent-heartbeat"]);
  });

  it("normalizes window and trigger query params", () => {
    expect(normalizeRunWindow("bogus")).toBe("24h");
    expect(normalizeRunWindow("7d")).toBe("7d");
    expect(windowToHours("30d")).toBe(720);
    expect(getRunWindowStart("4h", 1_000_000)).toBe(1_000_000 - 14_400_000);
    expect(normalizeRunTriggerFilter("heartbeat")).toBe("heartbeat");
    expect(normalizeRunTriggerFilter("bogus")).toBe("all");
  });
});
