"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { compareRuns, type RunCompareData, type RunDiffHunk } from "@/lib/runs";

function DiffLine({ line }: { line: string }) {
  const prefix = line.charAt(0);
  const bg =
    prefix === "+"
      ? "bg-green-900/30 text-green-300"
      : prefix === "-"
        ? "bg-red-900/30 text-red-300"
        : "text-zinc-300";
  return (
    <pre className={`px-3 py-0.5 text-sm font-mono whitespace-pre-wrap ${bg}`}>
      {line}
    </pre>
  );
}

function DiffPanel({ hunks }: { hunks: RunDiffHunk[] }) {
  if (hunks.length === 0) {
    return (
      <div className="p-4 text-zinc-500 text-sm">No differences found.</div>
    );
  }
  return (
    <div className="space-y-3">
      {hunks.map((hunk, i) => (
        <div key={i} className="rounded border border-zinc-800">
          <div className="px-3 py-1.5 bg-zinc-900 text-zinc-400 text-xs font-mono border-b border-zinc-800">
            {hunk.header}
          </div>
          <div className="divide-y divide-zinc-800/50">
            {hunk.lines.map((line, j) => (
              <DiffLine key={j} line={line} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function OutputPanel({
  title,
  output,
  runId,
}: {
  title: string;
  output: string;
  runId: string;
}) {
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-sm font-medium text-zinc-300">{title}</h3>
        <span className="text-xs font-mono text-zinc-600">{runId}</span>
      </div>
      <div className="rounded border border-zinc-800 bg-zinc-950 p-3 max-h-[60vh] overflow-auto">
        <pre className="text-sm font-mono text-zinc-300 whitespace-pre-wrap">
          {output || "(empty)"}
        </pre>
      </div>
    </div>
  );
}

export default function ComparePage() {
  const searchParams = useSearchParams();
  const runA = searchParams.get("run_a") ?? "";
  const runB = searchParams.get("run_b") ?? "";

  const [data, setData] = useState<RunCompareData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"side-by-side" | "diff">(
    "side-by-side",
  );

  const fetchCompare = useCallback(async () => {
    if (!runA || !runB) return;
    setLoading(true);
    setError(null);
    try {
      const result = await compareRuns(runA, runB);
      setData(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to compare runs",
      );
    } finally {
      setLoading(false);
    }
  }, [runA, runB]);

  useEffect(() => {
    fetchCompare();
  }, [fetchCompare]);

  if (!runA || !runB) {
    return (
      <div className="p-8 text-center text-zinc-400">
        <p className="text-lg mb-2">Run Compare</p>
        <p className="text-sm">
          Provide <code className="text-zinc-300">run_a</code> and{" "}
          <code className="text-zinc-300">run_b</code> query parameters.
        </p>
        <p className="text-xs mt-2 text-zinc-600">
          Example:{" "}
          <code>/runs/compare?run_a=abc123&amp;run_b=def456</code>
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-200">Compare Runs</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode("side-by-side")}
            className={`px-3 py-1.5 text-xs rounded ${
              viewMode === "side-by-side"
                ? "bg-zinc-700 text-zinc-200"
                : "bg-zinc-900 text-zinc-500 hover:text-zinc-300"
            }`}
          >
            Side-by-Side
          </button>
          <button
            onClick={() => setViewMode("diff")}
            className={`px-3 py-1.5 text-xs rounded ${
              viewMode === "diff"
                ? "bg-zinc-700 text-zinc-200"
                : "bg-zinc-900 text-zinc-500 hover:text-zinc-300"
            }`}
          >
            Unified Diff
          </button>
          {data && (
            <span className="text-xs text-zinc-500 ml-2">
              +{data.diff.total_additions} -{data.diff.total_deletions}
            </span>
          )}
        </div>
      </div>

      {loading && <div className="text-zinc-500 text-sm">Loading...</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {data && viewMode === "side-by-side" && (
        <div className="flex gap-4">
          <OutputPanel
            title="Run A"
            output={data.run_a.output}
            runId={data.run_a.run_id}
          />
          <OutputPanel
            title="Run B"
            output={data.run_b.output}
            runId={data.run_b.run_id}
          />
        </div>
      )}

      {data && viewMode === "diff" && <DiffPanel hunks={data.diff.hunks} />}

      {data && (
        <div className="grid grid-cols-2 gap-4 pt-4 border-t border-zinc-800">
          <div>
            <h4 className="text-xs text-zinc-500 mb-1">Tool Calls (Run A)</h4>
            <div className="text-xs text-zinc-400 space-y-1">
              {data.run_a.tool_calls.map((tc, i) => (
                <div key={i} className="font-mono">
                  {(tc as Record<string, unknown>).tool_name as string} —{" "}
                  {(tc as Record<string, unknown>).status as string}
                </div>
              ))}
              {data.run_a.tool_calls.length === 0 && (
                <span className="text-zinc-600">None</span>
              )}
            </div>
          </div>
          <div>
            <h4 className="text-xs text-zinc-500 mb-1">Tool Calls (Run B)</h4>
            <div className="text-xs text-zinc-400 space-y-1">
              {data.run_b.tool_calls.map((tc, i) => (
                <div key={i} className="font-mono">
                  {(tc as Record<string, unknown>).tool_name as string} —{" "}
                  {(tc as Record<string, unknown>).status as string}
                </div>
              ))}
              {data.run_b.tool_calls.length === 0 && (
                <span className="text-zinc-600">None</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
