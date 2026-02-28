"use client";

import { useEffect, useMemo, useState } from "react";

import { Navbar } from "@/components/layout/Navbar";
import {
  Badge,
  Button,
  DataTable,
  Select,
  TableWrap,
} from "@/components/ui/primitives";
import {
  getAgents,
  getUsageRecords,
  getUsageSummary,
  UsageRecord,
  UsageSummary,
} from "@/lib/api";

const TIMEFRAME_OPTIONS = [
  { label: "Last 1 hour", value: 1 },
  { label: "Last 24 hours", value: 24 },
  { label: "Last 7 days", value: 24 * 7 },
  { label: "Last 30 days", value: 24 * 30 },
];

const usdFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 6,
  maximumFractionDigits: 6,
});

const numberFormatter = new Intl.NumberFormat("en-US");

const utcTimeFormatter = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  hour12: false,
});

function formatUsd(value: number): string {
  return usdFormatter.format(value);
}

function formatUsdMaybe(value: number | null): string {
  if (value === null) return "Unpriced";
  return formatUsd(value);
}

function formatNumber(value: number): string {
  return numberFormatter.format(value);
}

function formatUtcTimestamp(timestampMs: number): string {
  return utcTimeFormatter.format(new Date(timestampMs));
}

function buildTrendBuckets(records: UsageRecord[], sinceHours: number) {
  if (records.length === 0) return [];
  const bucketHours = sinceHours <= 48 ? 1 : 24;
  const bucketMs = bucketHours * 60 * 60 * 1000;
  const now = Date.now();
  const start = now - sinceHours * 60 * 60 * 1000;
  const buckets: Array<{
    label: string;
    total_tokens: number;
    cost_usd: number;
  }> = [];
  const map = new Map<number, { total_tokens: number; cost_usd: number }>();

  for (const row of records) {
    if (row.timestamp_ms < start) continue;
    const offset = Math.floor((row.timestamp_ms - start) / bucketMs);
    const key = start + offset * bucketMs;
    const current = map.get(key) ?? { total_tokens: 0, cost_usd: 0 };
    current.total_tokens += row.total_tokens;
    if (row.cost_usd !== null) {
      current.cost_usd += row.cost_usd;
    }
    map.set(key, current);
  }

  const count = Math.max(1, Math.ceil((now - start) / bucketMs));
  for (let i = 0; i < count; i += 1) {
    const ts = start + i * bucketMs;
    const row = map.get(ts) ?? { total_tokens: 0, cost_usd: 0 };
    buckets.push({
      label:
        bucketHours === 1
          ? new Date(ts).toISOString().slice(5, 13).replace("T", " ")
          : new Date(ts).toISOString().slice(0, 10),
      total_tokens: row.total_tokens,
      cost_usd: row.cost_usd,
    });
  }
  return buckets;
}

function toCsv(records: UsageRecord[]): string {
  const header = [
    "timestamp_ms",
    "provider",
    "model",
    "run_id",
    "session_id",
    "trigger_type",
    "input_tokens",
    "input_uncached_tokens",
    "input_cache_read_tokens",
    "input_cache_write_tokens_5m",
    "input_cache_write_tokens_1h",
    "input_cache_write_tokens_unknown",
    "output_tokens",
    "reasoning_tokens",
    "tool_input_tokens",
    "total_tokens",
    "priced",
    "cost_usd",
  ];
  const rows = records.map((row) =>
    [
      row.timestamp_ms,
      row.provider,
      row.model,
      row.run_id,
      row.session_id,
      row.trigger_type,
      row.input_tokens,
      row.input_uncached_tokens,
      row.input_cache_read_tokens,
      row.input_cache_write_tokens_5m,
      row.input_cache_write_tokens_1h,
      row.input_cache_write_tokens_unknown,
      row.output_tokens,
      row.reasoning_tokens,
      row.tool_input_tokens,
      row.total_tokens,
      row.priced,
      row.cost_usd ?? "",
    ]
      .map((item) => `"${String(item).replace(/"/g, '""')}"`)
      .join(","),
  );
  return [header.join(","), ...rows].join("\n");
}

export default function UsagePage() {
  const [agents, setAgents] = useState<string[]>(["default"]);
  const [agentId, setAgentId] = useState<string>("default");
  const [sinceHours, setSinceHours] = useState<number>(24);
  const [provider, setProvider] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [triggerType, setTriggerType] = useState<string>("");
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [records, setRecords] = useState<UsageRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [copyState, setCopyState] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    async function loadAgents() {
      try {
        const rows = await getAgents();
        if (cancelled) return;
        const ids = rows.map((item) => item.agent_id);
        setAgents(ids.length > 0 ? ids : ["default"]);
        if (ids.length > 0 && !ids.includes(agentId)) {
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
    let cancelled = false;

    async function run() {
      setLoading(true);
      setError("");
      try {
        const [summaryData, recordsData] = await Promise.all([
          getUsageSummary({
            sinceHours,
            provider: provider || undefined,
            model: model || undefined,
            triggerType: triggerType || undefined,
            agentId,
          }),
          getUsageRecords({
            sinceHours,
            provider: provider || undefined,
            model: model || undefined,
            triggerType: triggerType || undefined,
            limit: 300,
            agentId,
          }),
        ]);
        if (cancelled) return;
        setSummary(summaryData);
        setRecords(recordsData);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load usage data",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [agentId, model, provider, sinceHours, triggerType]);

  useEffect(() => {
    if (!copyState) return;
    const timer = setTimeout(() => setCopyState(""), 1800);
    return () => {
      clearTimeout(timer);
    };
  }, [copyState]);

  const providerOptions = useMemo(() => {
    const values = new Set<string>();
    for (const row of summary?.by_provider ?? []) {
      values.add(row.provider);
    }
    for (const row of records) {
      values.add(row.provider);
    }
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }, [summary, records]);

  const modelOptions = useMemo(() => {
    const values = new Set<string>();
    for (const row of summary?.by_provider_model ?? []) {
      if (provider && row.provider !== provider) continue;
      values.add(row.model);
    }
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }, [provider, summary]);

  const totals = summary?.totals ?? {
    runs: 0,
    priced_runs: 0,
    unpriced_runs: 0,
    input_tokens: 0,
    input_uncached_tokens: 0,
    input_cache_read_tokens: 0,
    input_cache_write_tokens_5m: 0,
    input_cache_write_tokens_1h: 0,
    input_cache_write_tokens_unknown: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    tool_input_tokens: 0,
    total_tokens: 0,
    cost_usd: 0,
  };

  const trendBuckets = useMemo(
    () => buildTrendBuckets(records, sinceHours),
    [records, sinceHours],
  );
  const maxTrend = useMemo(
    () => Math.max(1, ...trendBuckets.map((item) => item.total_tokens)),
    [trendBuckets],
  );

  async function copyRunId(runId: string) {
    try {
      await navigator.clipboard.writeText(runId);
      setCopyState(runId);
    } catch {
      setCopyState("");
    }
  }

  function exportCsv() {
    const blob = new Blob([toCsv(records)], { type: "text/csv;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `usage-${agentId}-${sinceHours}h.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
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
            <h1 className="ui-panel-title">Usage Analytics</h1>
            <div className="flex flex-wrap items-center gap-2">
              {loading ? (
                <Badge tone="accent">Running</Badge>
              ) : (
                <Badge tone="success">Ready</Badge>
              )}
              {error ? <Badge tone="danger">Error</Badge> : null}
              <Badge tone="neutral">Records {records.length}</Badge>
              <Button
                type="button"
                className="min-h-[28px] px-2 text-[11px]"
                disabled={records.length === 0}
                onClick={exportCsv}
              >
                Export CSV
              </Button>
            </div>
          </div>

          <div className="grid gap-3 p-4 md:grid-cols-6">
            <label className="min-w-0">
              <span className="ui-label">Agent</span>
              <Select
                name="agent-filter"
                className="mt-1 ui-mono text-xs"
                value={agentId}
                onChange={(event) => setAgentId(event.target.value)}
              >
                {agents.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            </label>

            <label className="min-w-0">
              <span className="ui-label">Timeframe</span>
              <Select
                name="timeframe-filter"
                className="mt-1 text-xs"
                value={String(sinceHours)}
                onChange={(event) => setSinceHours(Number(event.target.value))}
              >
                {TIMEFRAME_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>

            <label className="min-w-0">
              <span className="ui-label">Provider</span>
              <Select
                name="provider-filter"
                className="mt-1 ui-mono text-xs"
                value={provider}
                onChange={(event) => {
                  setProvider(event.target.value);
                  setModel("");
                }}
              >
                <option value="">All providers</option>
                {providerOptions.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            </label>

            <label className="min-w-0">
              <span className="ui-label">Model</span>
              <Select
                name="model-filter"
                className="mt-1 ui-mono text-xs"
                value={model}
                onChange={(event) => setModel(event.target.value)}
              >
                <option value="">All models</option>
                {modelOptions.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            </label>

            <label className="min-w-0">
              <span className="ui-label">Trigger</span>
              <Select
                name="trigger-filter"
                className="mt-1 ui-mono text-xs"
                value={triggerType}
                onChange={(event) => setTriggerType(event.target.value)}
              >
                <option value="">All triggers</option>
                <option value="chat">chat</option>
                <option value="heartbeat">heartbeat</option>
                <option value="cron">cron</option>
              </Select>
            </label>

            <div className="min-w-0">
              <div className="ui-label">Status</div>
              <div className="mt-1 flex min-h-[38px] items-center gap-2 rounded-[var(--radius-2)] border border-[var(--border)] bg-[var(--surface-3)] px-3">
                {loading ? (
                  <Badge tone="accent">Loading…</Badge>
                ) : (
                  <Badge tone="neutral">Loaded</Badge>
                )}
                {error ? (
                  <span className="truncate text-xs text-[var(--danger)]">
                    {error}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-5">
          <div className="panel-shell p-4">
            <div className="ui-label">Priced Cost (USD)</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {formatUsd(totals.cost_usd)}
            </div>
            <div className="mt-1 text-[11px] text-[var(--muted)]">
              Priced runs {formatNumber(totals.priced_runs)} /{" "}
              {formatNumber(totals.runs)}
            </div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Input Tokens</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {formatNumber(totals.input_tokens)}
            </div>
            <div className="mt-1 text-[11px] text-[var(--muted)]">
              Uncached {formatNumber(totals.input_uncached_tokens)}
            </div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Cache Read</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {formatNumber(totals.input_cache_read_tokens)}
            </div>
            <div className="mt-1 text-[11px] text-[var(--muted)]">
              Cache Write {" "}
              {formatNumber(
                totals.input_cache_write_tokens_5m +
                  totals.input_cache_write_tokens_1h +
                  totals.input_cache_write_tokens_unknown,
              )}
            </div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Output Tokens</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {formatNumber(totals.output_tokens)}
            </div>
            <div className="mt-1 text-[11px] text-[var(--muted)]">
              Reasoning {formatNumber(totals.reasoning_tokens)}
            </div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Total / Tool Input</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {formatNumber(totals.total_tokens)} /{" "}
              {formatNumber(totals.tool_input_tokens)}
            </div>
            <div className="mt-1 text-[11px] text-[var(--muted)]">
              Unpriced runs {formatNumber(totals.unpriced_runs)}
            </div>
          </div>
        </div>

        <div className="panel-shell">
          <div className="ui-panel-header">
            <h2 className="ui-panel-title">Token Trend</h2>
            <Badge tone="neutral">{trendBuckets.length} buckets</Badge>
          </div>
          <div className="p-4">
            <div className="h-32 w-full">
              <svg
                viewBox={`0 0 ${Math.max(1, trendBuckets.length)} 100`}
                preserveAspectRatio="none"
                className="h-full w-full"
              >
                {trendBuckets.map((bucket, index) => {
                  const height = (bucket.total_tokens / maxTrend) * 92;
                  const y = 96 - height;
                  return (
                    <g key={`${bucket.label}-${index}`}>
                      <rect
                        x={index + 0.12}
                        y={y}
                        width={0.76}
                        height={Math.max(2, height)}
                        rx={0.1}
                        fill="var(--accent)"
                        opacity={0.85}
                      />
                    </g>
                  );
                })}
              </svg>
            </div>
            <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[var(--muted)]">
              {trendBuckets
                .slice(Math.max(0, trendBuckets.length - 6))
                .map((bucket) => (
                  <span
                    key={bucket.label}
                    className="rounded border border-[var(--border)] px-2 py-0.5"
                  >
                    {bucket.label}: {formatNumber(bucket.total_tokens)} ({" "}
                    {formatUsd(bucket.cost_usd)})
                  </span>
                ))}
            </div>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-2">
          <div className="panel-shell min-h-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">By Provider / Model</h2>
              <Badge tone="neutral">
                {summary?.by_provider_model.length ?? 0} rows
              </Badge>
            </div>
            <TableWrap className="m-3 mt-0 max-h-full">
              <DataTable>
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Model</th>
                    <th>Runs</th>
                    <th>Input</th>
                    <th>Cache Read</th>
                    <th>Output</th>
                    <th>Total</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {(summary?.by_provider_model ?? []).map((row) => (
                    <tr key={`${row.provider}:${row.model}`}>
                      <td className="ui-mono">{row.provider}</td>
                      <td className="ui-mono">{row.model}</td>
                      <td>
                        {formatNumber(row.runs)} ({formatNumber(row.priced_runs)}p)
                      </td>
                      <td>{formatNumber(row.input_tokens)}</td>
                      <td>{formatNumber(row.input_cache_read_tokens)}</td>
                      <td>{formatNumber(row.output_tokens)}</td>
                      <td>{formatNumber(row.total_tokens)}</td>
                      <td>{formatUsd(row.cost_usd)}</td>
                    </tr>
                  ))}
                  {(summary?.by_provider_model ?? []).length === 0 ? (
                    <tr>
                      <td
                        colSpan={8}
                        className="text-center text-[var(--muted)]"
                      >
                        No model data for this filter.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </DataTable>
            </TableWrap>
          </div>

          <div className="panel-shell min-h-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">Recent Runs</h2>
              <Badge tone="neutral">last {records.length}</Badge>
            </div>
            <TableWrap className="m-3 mt-0 max-h-full">
              <DataTable>
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Time (UTC)</th>
                    <th>Provider / Model</th>
                    <th>Input</th>
                    <th>Output</th>
                    <th>Total</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((row, index) => (
                    <tr key={`${row.run_id}-${index}`}>
                      <td className="ui-mono">
                        <div className="flex items-center gap-2">
                          <span>{row.run_id.slice(0, 8)}</span>
                          <Button
                            type="button"
                            className="min-h-[24px] px-2 text-[10px]"
                            aria-label={`Copy run id ${row.run_id}`}
                            onClick={() => {
                              void copyRunId(row.run_id);
                            }}
                          >
                            Copy
                          </Button>
                        </div>
                        {copyState === row.run_id ? (
                          <div
                            className="mt-1 text-[10px] text-[var(--success)]"
                            aria-live="polite"
                          >
                            Copied
                          </div>
                        ) : null}
                      </td>
                      <td>{formatUtcTimestamp(row.timestamp_ms)}</td>
                      <td className="ui-mono">
                        {row.provider}
                        <div>{row.model}</div>
                      </td>
                      <td>
                        {formatNumber(row.input_tokens)}
                        <div className="text-[10px] text-[var(--muted)]">
                          u:{formatNumber(row.input_uncached_tokens)} r:
                          {formatNumber(row.input_cache_read_tokens)} w:
                          {formatNumber(
                            row.input_cache_write_tokens_5m +
                              row.input_cache_write_tokens_1h +
                              row.input_cache_write_tokens_unknown,
                          )}
                        </div>
                      </td>
                      <td>
                        {formatNumber(row.output_tokens)}
                        <div className="text-[10px] text-[var(--muted)]">
                          reasoning {formatNumber(row.reasoning_tokens)}
                        </div>
                      </td>
                      <td>{formatNumber(row.total_tokens)}</td>
                      <td>
                        {formatUsdMaybe(row.cost_usd)}
                        {!row.priced ? (
                          <div className="text-[10px] text-[var(--danger)]">
                            {row.pricing.unpriced_reason ?? "unpriced"}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                  {records.length === 0 ? (
                    <tr>
                      <td
                        colSpan={7}
                        className="text-center text-[var(--muted)]"
                      >
                        No recent runs for this filter.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </DataTable>
            </TableWrap>
          </div>
        </div>
      </section>
    </main>
  );
}
