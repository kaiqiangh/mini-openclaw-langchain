"use client";

import { useEffect, useMemo, useState } from "react";

import { Navbar } from "@/components/layout/Navbar";
import { Badge, Button, DataTable, Select, TableWrap } from "@/components/ui/primitives";
import { getAgents, getUsageRecords, getUsageSummary, UsageRecord, UsageSummary } from "@/lib/api";

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

function formatUsd(value: number): string {
  return usdFormatter.format(value);
}

function formatNumber(value: number): string {
  return numberFormatter.format(value);
}

export default function UsagePage() {
  const [agents, setAgents] = useState<string[]>(["default"]);
  const [agentId, setAgentId] = useState<string>("default");
  const [sinceHours, setSinceHours] = useState<number>(24);
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
          getUsageSummary({ sinceHours, model: model || undefined, triggerType: triggerType || undefined, agentId }),
          getUsageRecords({
            sinceHours,
            model: model || undefined,
            triggerType: triggerType || undefined,
            limit: 200,
            agentId,
          }),
        ]);
        if (cancelled) return;
        setSummary(summaryData);
        setRecords(recordsData);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load usage data");
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
  }, [agentId, model, sinceHours, triggerType]);

  useEffect(() => {
    if (!copyState) return;
    const timer = setTimeout(() => setCopyState(""), 1800);
    return () => {
      clearTimeout(timer);
    };
  }, [copyState]);

  const modelOptions = useMemo(() => {
    const items = new Set<string>();
    for (const row of summary?.by_model ?? []) {
      items.add(row.model);
    }
    return Array.from(items).sort((a, b) => a.localeCompare(b));
  }, [summary]);

  const totals = summary?.totals ?? {
    runs: 0,
    input_tokens: 0,
    cached_input_tokens: 0,
    uncached_input_tokens: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 0,
    estimated_cost_usd: 0,
  };

  async function copyRunId(runId: string) {
    try {
      await navigator.clipboard.writeText(runId);
      setCopyState(runId);
    } catch {
      setCopyState("");
    }
  }

  return (
    <main id="main-content" className="app-main flex h-screen flex-col overflow-hidden">
      <Navbar />
      <section className="flex h-full min-h-0 flex-col gap-3 p-3">
        <div className="panel-shell">
          <div className="ui-panel-header">
            <h1 className="ui-panel-title">Usage Analytics</h1>
            <div className="flex flex-wrap items-center gap-2">
              {loading ? <Badge tone="accent">Running</Badge> : <Badge tone="success">Ready</Badge>}
              {error ? <Badge tone="danger">Error</Badge> : null}
              <Badge tone="neutral">Records {records.length}</Badge>
            </div>
          </div>

          <div className="grid gap-3 p-4 md:grid-cols-5">
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
                {loading ? <Badge tone="accent">Loading…</Badge> : <Badge tone="neutral">Loaded</Badge>}
                {error ? <span className="truncate text-xs text-[var(--danger)]">{error}</span> : null}
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-5">
          <div className="panel-shell p-4">
            <div className="ui-label">Estimated Cost</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">{formatUsd(totals.estimated_cost_usd)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Input Tokens</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">{formatNumber(totals.input_tokens)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Cached Input</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">{formatNumber(totals.cached_input_tokens)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Output Tokens</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">{formatNumber(totals.output_tokens)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="ui-label">Reasoning / Total</div>
            <div className="ui-tabular mt-1 text-lg font-semibold">
              {formatNumber(totals.reasoning_tokens)} / {formatNumber(totals.total_tokens)}
            </div>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-2">
          <div className="panel-shell min-h-0">
            <div className="ui-panel-header">
              <h2 className="ui-panel-title">By Model</h2>
              <Badge tone="neutral">{summary?.by_model.length ?? 0} models</Badge>
            </div>
            <TableWrap className="m-3 mt-0 max-h-full">
              <DataTable>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Runs</th>
                    <th>Input</th>
                    <th>Cached</th>
                    <th>Output</th>
                    <th>Total</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {(summary?.by_model ?? []).map((row) => (
                    <tr key={row.model}>
                      <td className="ui-mono">{row.model}</td>
                      <td>{formatNumber(row.runs)}</td>
                      <td>{formatNumber(row.input_tokens)}</td>
                      <td>{formatNumber(row.cached_input_tokens)}</td>
                      <td>{formatNumber(row.output_tokens)}</td>
                      <td>{formatNumber(row.total_tokens)}</td>
                      <td>{formatUsd(row.estimated_cost_usd)}</td>
                    </tr>
                  ))}
                  {(summary?.by_model ?? []).length === 0 ? (
                    <tr>
                      <td colSpan={7} className="text-center text-[var(--muted)]">
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
                    <th>Time</th>
                    <th>Model</th>
                    <th>Input</th>
                    <th>Cached</th>
                    <th>Output</th>
                    <th>Reasoning</th>
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
                          <div className="mt-1 text-[10px] text-[var(--success)]" aria-live="polite">
                            Copied
                          </div>
                        ) : null}
                      </td>
                      <td>{new Date(row.timestamp_ms).toLocaleString()}</td>
                      <td className="ui-mono">{row.model}</td>
                      <td>{formatNumber(row.input_tokens)}</td>
                      <td>{formatNumber(row.cached_input_tokens)}</td>
                      <td>{formatNumber(row.output_tokens)}</td>
                      <td>{formatNumber(row.reasoning_tokens)}</td>
                      <td>{formatNumber(row.total_tokens)}</td>
                      <td>{formatUsd(row.estimated_cost_usd)}</td>
                    </tr>
                  ))}
                  {records.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="text-center text-[var(--muted)]">
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
