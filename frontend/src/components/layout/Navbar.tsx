"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAppStore } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";
import { getTracingConfig, setTracingConfig } from "@/lib/api";

export function Navbar() {
  const { ragEnabled, toggleRag, isStreaming, currentAgentId } = useAppStore();
  const pathname = usePathname();
  const [traceEnabled, setTraceEnabled] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceUnavailable, setTraceUnavailable] = useState(false);

  const workspaceActive = pathname === "/";
  const usageActive = pathname?.startsWith("/usage");
  const schedulerActive = pathname?.startsWith("/scheduler");

  useEffect(() => {
    let cancelled = false;
    if (!workspaceActive) return;
    setTraceLoading(true);
    void getTracingConfig()
      .then((config) => {
        if (cancelled) return;
        setTraceEnabled(Boolean(config.enabled));
        setTraceUnavailable(false);
      })
      .catch(() => {
        if (cancelled) return;
        setTraceUnavailable(true);
      })
      .finally(() => {
        if (cancelled) return;
        setTraceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceActive]);

  return (
    <header className="z-20 flex h-14 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-2)] px-4 backdrop-blur-md">
      <div className="flex min-w-0 items-center gap-3">
        <div className="min-w-0 text-sm font-semibold tracking-[0.06em] text-[var(--text)]">
          mini OpenClaw
        </div>
        <Badge tone="neutral" className="max-w-[220px] truncate">
          Agent: {currentAgentId}
        </Badge>
        {isStreaming ? (
          <Badge tone="accent">Running</Badge>
        ) : (
          <Badge tone="success">Idle</Badge>
        )}
        <nav className="flex items-center gap-2 text-xs">
          <Link
            href="/"
            className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition-colors duration-200 ${
              workspaceActive
                ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                : "border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text)]"
            }`}
          >
            Workspace
          </Link>
          <Link
            href="/usage"
            className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition-colors duration-200 ${
              usageActive
                ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                : "border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text)]"
            }`}
          >
            Usage
          </Link>
          <Link
            href="/scheduler"
            className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition-colors duration-200 ${
              schedulerActive
                ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                : "border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text)]"
            }`}
          >
            Scheduler
          </Link>
        </nav>
      </div>
      <div className="flex items-center gap-3">
        {workspaceActive ? (
          <>
            <button
              type="button"
              aria-label="Toggle RAG mode"
              title="Retrieval-augmented generation"
              disabled={isStreaming}
              onClick={() => {
                void toggleRag(!ragEnabled);
              }}
              className={`group inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors duration-200 ${
                ragEnabled
                  ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                  : "border-[var(--border)] bg-[var(--surface-3)] text-[var(--muted)] hover:text-[var(--text)]"
              } ${isStreaming ? "cursor-not-allowed opacity-60" : "hover:border-[var(--accent)]"}`}
            >
              <span
                aria-hidden
                className={`inline-flex h-5 w-5 items-center justify-center rounded-full border ${
                  ragEnabled
                    ? "border-[var(--accent-strong)] bg-[var(--accent)]/20"
                    : "border-[var(--border-strong)] bg-[var(--surface-2)]"
                }`}
              >
                <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="none">
                  <path
                    d="M3.5 8.5a6.5 6.5 0 0 1 13 0v3.25a1.75 1.75 0 0 1-1.75 1.75h-9.5a1.75 1.75 0 0 1-1.75-1.75V8.5Z"
                    stroke="currentColor"
                    strokeWidth="1.4"
                  />
                  <path
                    d="M7.25 6.5h5.5M10 6.5v7"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                  />
                </svg>
              </span>
              <span className="ui-mono tracking-[0.04em]">
                RAG {ragEnabled ? "ON" : "OFF"}
              </span>
            </button>
            <button
              type="button"
              aria-label="Toggle LangSmith tracing"
              title={
                traceUnavailable
                  ? "Tracing config unavailable"
                  : "Toggle LangSmith tracing"
              }
              disabled={traceLoading}
              onClick={() => {
                if (traceLoading) return;
                const nextEnabled = !traceEnabled;
                setTraceLoading(true);
                void setTracingConfig(nextEnabled)
                  .then((config) => {
                    setTraceEnabled(Boolean(config.enabled));
                    setTraceUnavailable(false);
                  })
                  .catch(() => {
                    setTraceUnavailable(true);
                  })
                  .finally(() => {
                    setTraceLoading(false);
                  });
              }}
              className={`group inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors duration-200 ${
                traceEnabled
                  ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                  : "border-[var(--border)] bg-[var(--surface-3)] text-[var(--muted)] hover:text-[var(--text)]"
              } ${traceLoading ? "cursor-not-allowed opacity-60" : "hover:border-[var(--accent)]"}`}
            >
              <span
                aria-hidden
                className={`inline-flex h-5 w-5 items-center justify-center rounded-full border ${
                  traceEnabled
                    ? "border-[var(--accent-strong)] bg-[var(--accent)]/20"
                    : "border-[var(--border-strong)] bg-[var(--surface-2)]"
                }`}
              >
                <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="none">
                  <path
                    d="M3.75 6.25h12.5v7.5H3.75z"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    rx="1.5"
                  />
                  <path
                    d="M7 10h6M8.5 13.25h3"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                  />
                </svg>
              </span>
              <span className="ui-mono tracking-[0.04em]">
                Trace {traceEnabled ? "ON" : "OFF"}
              </span>
            </button>
          </>
        ) : null}
      </div>
    </header>
  );
}
