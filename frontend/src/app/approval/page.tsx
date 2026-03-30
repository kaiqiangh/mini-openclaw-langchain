"use client";

import { useCallback, useEffect, useState } from "react";
import {
  listApprovals,
  resolveApproval,
  type ApprovalRequest,
} from "@/lib/api";

function formatTime(timestampMs: number): string {
  const date = new Date(timestampMs * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 0) return "{}";
  return entries
    .map(([k, v]) => {
      const val = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}: ${val.length > 60 ? val.slice(0, 60) + "…" : val}`;
    })
    .join(", ");
}

function ApprovalCard({
  request,
  onResolve,
}: {
  request: ApprovalRequest;
  onResolve: (
    requestId: string,
    action: "approve" | "deny",
    reason?: string,
  ) => void;
}) {
  const [showDenyReason, setShowDenyReason] = useState(false);
  const [denyReason, setDenyReason] = useState("");

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-zinc-200">
            {request.tool_name}
          </span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
            {request.trigger_type}
          </span>
        </div>
        <span className="text-xs text-zinc-500">
          {formatTime(request.created_at)}
        </span>
      </div>

      <div className="text-xs text-zinc-400 font-mono bg-zinc-950 rounded p-2">
        {formatArgs(request.tool_args)}
      </div>

      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <span>Session: {request.session_id.slice(0, 8)}…</span>
        {request.run_id && <span>Run: {request.run_id.slice(0, 8)}…</span>}
      </div>

      {showDenyReason ? (
        <div className="space-y-2">
          <input
            type="text"
            value={denyReason}
            onChange={(e) => setDenyReason(e.target.value)}
            placeholder="Reason for denial (optional)"
            className="w-full px-2 py-1.5 text-sm bg-zinc-950 border border-zinc-700 rounded text-zinc-200 focus:outline-none focus:border-zinc-500"
          />
          <div className="flex gap-2">
            <button
              onClick={() => {
                onResolve(request.request_id, "deny", denyReason || undefined);
                setShowDenyReason(false);
                setDenyReason("");
              }}
              className="px-3 py-1.5 text-xs rounded bg-red-600 text-white hover:bg-red-500"
            >
              Confirm Deny
            </button>
            <button
              onClick={() => {
                setShowDenyReason(false);
                setDenyReason("");
              }}
              className="px-3 py-1.5 text-xs rounded bg-zinc-800 text-zinc-400 hover:text-zinc-200"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={() => onResolve(request.request_id, "approve")}
            className="px-3 py-1.5 text-xs rounded bg-green-600 text-white hover:bg-green-500"
          >
            Approve
          </button>
          <button
            onClick={() => setShowDenyReason(true)}
            className="px-3 py-1.5 text-xs rounded bg-zinc-800 text-zinc-400 hover:text-red-400"
          >
            Deny
          </button>
        </div>
      )}
    </div>
  );
}

export default function ApprovalPage() {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchApprovals = useCallback(async () => {
    try {
      const result = await listApprovals();
      setApprovals(result);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch approvals",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchApprovals();
    const interval = setInterval(fetchApprovals, 5000);
    return () => clearInterval(interval);
  }, [fetchApprovals]);

  const handleResolve = useCallback(
    async (
      requestId: string,
      action: "approve" | "deny",
      reason?: string,
    ) => {
      try {
        await resolveApproval("default", requestId, { action, reason });
        // Optimistic removal
        setApprovals((prev) =>
          prev.filter((a) => a.request_id !== requestId),
        );
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to resolve approval",
        );
        fetchApprovals(); // Rollback
      }
    },
    [fetchApprovals],
  );

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-200">Approvals</h2>
        <span className="text-xs text-zinc-500">
          {approvals.length} pending · auto-refresh 5s
        </span>
      </div>

      {loading && <div className="text-zinc-500 text-sm">Loading...</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {!loading && approvals.length === 0 && (
        <div className="text-center py-12 text-zinc-500 text-sm">
          No pending approvals
        </div>
      )}

      <div className="space-y-3">
        {approvals.map((req) => (
          <ApprovalCard
            key={req.request_id}
            request={req}
            onResolve={handleResolve}
          />
        ))}
      </div>
    </div>
  );
}
