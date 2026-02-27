"use client";

import { useEffect, useMemo, useState } from "react";

import { Navbar } from "@/components/layout/Navbar";
import { getAgents, getUsageRecords, getUsageSummary, UsageRecord, UsageSummary } from "@/lib/api";

const TIMEFRAME_OPTIONS = [
  { label: "Last 1 hour", value: 1 },
  { label: "Last 24 hours", value: 24 },
  { label: "Last 7 days", value: 24 * 7 },
  { label: "Last 30 days", value: 24 * 30 },
];

function formatUsd(value: number): string {
  return `$${value.toFixed(6)}`;
}

function formatNumber(value: number): string {
  return value.toLocaleString();
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

  return (
    <main className="flex h-screen flex-col overflow-hidden">
      <Navbar />
      <section className="flex h-full flex-col gap-3 p-3">
        <div className="panel-shell grid gap-3 p-4 md:grid-cols-5">
          <label className="text-xs text-gray-600">
            Agent
            <select
              className="mt-1 w-full rounded border border-gray-300 bg-white px-2 py-2 text-xs"
              value={agentId}
              onChange={(event) => setAgentId(event.target.value)}
            >
              {agents.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label className="text-xs text-gray-600">
            Timeframe
            <select
              className="mt-1 w-full rounded border border-gray-300 bg-white px-2 py-2 text-xs"
              value={String(sinceHours)}
              onChange={(event) => setSinceHours(Number(event.target.value))}
            >
              {TIMEFRAME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-xs text-gray-600">
            Model
            <select
              className="mt-1 w-full rounded border border-gray-300 bg-white px-2 py-2 text-xs"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              <option value="">All models</option>
              {modelOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label className="text-xs text-gray-600">
            Trigger
            <select
              className="mt-1 w-full rounded border border-gray-300 bg-white px-2 py-2 text-xs"
              value={triggerType}
              onChange={(event) => setTriggerType(event.target.value)}
            >
              <option value="">All triggers</option>
              <option value="chat">chat</option>
              <option value="heartbeat">heartbeat</option>
              <option value="cron">cron</option>
            </select>
          </label>

          <div className="text-xs text-gray-500">
            <div className="font-semibold text-gray-700">Status</div>
            <div className="mt-2">{loading ? "Loading usage..." : `Records: ${records.length}`}</div>
            {error ? <div className="mt-1 text-red-600">{error}</div> : null}
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-5">
          <div className="panel-shell p-4">
            <div className="text-xs text-gray-500">Estimated Cost</div>
            <div className="mt-1 text-lg font-semibold">{formatUsd(totals.estimated_cost_usd)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="text-xs text-gray-500">Input Tokens</div>
            <div className="mt-1 text-lg font-semibold">{formatNumber(totals.input_tokens)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="text-xs text-gray-500">Cached Input</div>
            <div className="mt-1 text-lg font-semibold">{formatNumber(totals.cached_input_tokens)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="text-xs text-gray-500">Output Tokens</div>
            <div className="mt-1 text-lg font-semibold">{formatNumber(totals.output_tokens)}</div>
          </div>
          <div className="panel-shell p-4">
            <div className="text-xs text-gray-500">Reasoning / Total</div>
            <div className="mt-1 text-lg font-semibold">
              {formatNumber(totals.reasoning_tokens)} / {formatNumber(totals.total_tokens)}
            </div>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-2">
          <div className="panel-shell min-h-0 overflow-auto p-4">
            <h2 className="text-sm font-semibold">By Model</h2>
            <table className="mt-3 w-full text-left text-xs">
              <thead className="text-gray-500">
                <tr>
                  <th className="py-1">Model</th>
                  <th className="py-1">Runs</th>
                  <th className="py-1">Input</th>
                  <th className="py-1">Cached</th>
                  <th className="py-1">Output</th>
                  <th className="py-1">Total</th>
                  <th className="py-1">Cost</th>
                </tr>
              </thead>
              <tbody>
                {(summary?.by_model ?? []).map((row) => (
                  <tr key={row.model} className="border-t border-gray-100">
                    <td className="py-2">{row.model}</td>
                    <td className="py-2">{formatNumber(row.runs)}</td>
                    <td className="py-2">{formatNumber(row.input_tokens)}</td>
                    <td className="py-2">{formatNumber(row.cached_input_tokens)}</td>
                    <td className="py-2">{formatNumber(row.output_tokens)}</td>
                    <td className="py-2">{formatNumber(row.total_tokens)}</td>
                    <td className="py-2">{formatUsd(row.estimated_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel-shell min-h-0 overflow-auto p-4">
            <h2 className="text-sm font-semibold">Recent Runs</h2>
            <table className="mt-3 w-full text-left text-xs">
              <thead className="text-gray-500">
                <tr>
                  <th className="py-1">Time</th>
                  <th className="py-1">Model</th>
                  <th className="py-1">Input</th>
                  <th className="py-1">Cached</th>
                  <th className="py-1">Output</th>
                  <th className="py-1">Reasoning</th>
                  <th className="py-1">Total</th>
                  <th className="py-1">Cost</th>
                </tr>
              </thead>
              <tbody>
                {records.map((row, index) => (
                  <tr key={`${row.run_id}-${index}`} className="border-t border-gray-100">
                    <td className="py-2">{new Date(row.timestamp_ms).toLocaleString()}</td>
                    <td className="py-2">{row.model}</td>
                    <td className="py-2">{formatNumber(row.input_tokens)}</td>
                    <td className="py-2">{formatNumber(row.cached_input_tokens)}</td>
                    <td className="py-2">{formatNumber(row.output_tokens)}</td>
                    <td className="py-2">{formatNumber(row.reasoning_tokens)}</td>
                    <td className="py-2">{formatNumber(row.total_tokens)}</td>
                    <td className="py-2">{formatUsd(row.estimated_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>
  );
}
