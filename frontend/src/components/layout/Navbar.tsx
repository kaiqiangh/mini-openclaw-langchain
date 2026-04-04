"use client";

import { useEffect, useState } from "react";

function useIsClaudeTheme() {
  const [isClaude, setIsClaude] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const checkTheme = () =>
      document.body.getAttribute("data-theme") === "claude";
    setIsClaude(checkTheme());
    const observer = new MutationObserver(checkTheme);
    observer.observe(document.body, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return isClaude;
}
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAppStore } from "@/lib/store";
import { activityTone } from "@/lib/badge-tones";
import { Badge } from "@/components/ui/primitives";
import { getTracingConfig, setTracingConfig } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/", label: "Agents", exact: true },
  { href: "/sessions", label: "Sessions", exact: false },
  { href: "/runs", label: "Runs", exact: false },
  { href: "/approval", label: "Approvals", exact: false },
  { href: "/traces", label: "Trace Explorer", exact: false },
  { href: "/scheduler", label: "Scheduler", exact: false },
  { href: "/usage", label: "Usage", exact: false },
] as const;

function isActivePath(
  pathname: string | null,
  href: (typeof NAV_ITEMS)[number]["href"],
  exact = false,
) {
  if (!pathname) return false;
  if (href === "/") {
    return pathname === "/";
  }
  return exact ? pathname === href : pathname.startsWith(href);
}

function navLinkClass(active: boolean) {
  if (active) {
    return 'inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-medium transition-colors duration-200 sm:text-sm';
  }
  return 'inline-flex items-center px-2 py-1.5 text-sm transition-colors duration-200 no-underline';
}

export function Navbar() {
  const isClaude = useIsClaudeTheme();
  const {
    ragEnabled,
    toggleRag,
    isStreaming,
    currentAgentId,
    currentSessionId,
    sessionsScope,
    maxStepsPrompt,
  } = useAppStore();
  const pathname = usePathname();
  const [traceEnabled, setTraceEnabled] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceUnavailable, setTraceUnavailable] = useState(false);

  const workspaceActive = pathname === "/";
  const runtimeLabel = isStreaming
    ? "Running"
    : maxStepsPrompt
      ? "Awaiting input"
      : sessionsScope === "archived"
        ? "Archived"
        : currentSessionId
          ? "Active"
          : "Idle";
  const runtimeTone = isStreaming
    ? activityTone("running")
    : maxStepsPrompt
      ? "warn"
      : sessionsScope === "archived"
        ? "warn"
        : currentSessionId
          ? activityTone("active")
          : activityTone("idle");
  const sessionsHref = (() => {
    const params = new URLSearchParams();
    if (currentAgentId) {
      params.set("agent", currentAgentId);
    }
    params.set("scope", sessionsScope);
    if (currentSessionId) {
      params.set("session", currentSessionId);
    }
    const query = params.toString();
    return query ? `/sessions?${query}` : "/sessions";
  })();

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
    <header className="z-20 border-b border-[var(--border)] bg-[var(--surface-2)]/95 backdrop-blur-md">
      <div className="flex flex-col gap-3 px-3 py-3 sm:px-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 sm:gap-3">
            <div className="flex min-w-0 items-center gap-2">
              {isClaude ? (
                <svg
                  width="32"
                  height="32"
                  viewBox="0 0 64 64"
                  className="flex-shrink-0"
                  aria-label="mini OpenClaw logo"
                >
                  <rect width="64" height="64" rx="14" fill="var(--accent, #c96442)" />
                  <path
                    d="M18 18 Q30 32 18 46"
                    fill="none"
                    stroke="var(--surface-1, #faf9f5)"
                    strokeWidth="4"
                    strokeLinecap="round"
                  />
                  <path
                    d="M28 14 Q40 32 28 50"
                    fill="none"
                    stroke="var(--surface-1, #faf9f5)"
                    strokeWidth="4"
                    strokeLinecap="round"
                  />
                  <path
                    d="M38 18 Q48 32 38 46"
                    fill="none"
                    stroke="var(--surface-1, #faf9f5)"
                    strokeWidth="4"
                    strokeLinecap="round"
                  />
                </svg>
              ) : null}
              <span
                className="min-w-0 text-sm sm:text-base"
                style={isClaude
                  ? { fontFamily: 'Georgia, serif', letterSpacing: '-0.005em', fontWeight: 500 }
                  : {}}
              >
                mini OpenClaw
              </span>
            </div>
            <Badge
              tone="neutral"
              className="hidden max-w-[220px] truncate sm:inline-flex"
            >
              Agent: {currentAgentId}
            </Badge>
            <Badge tone={runtimeTone}>{runtimeLabel}</Badge>
          </div>
          <div className="flex flex-shrink-0 items-center gap-2">
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
                  className={`group inline-flex min-h-[40px] items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors duration-200 sm:text-sm ${
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
                  <span className="ui-mono hidden tracking-[0.04em] sm:inline">
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
                  className={`group inline-flex min-h-[40px] items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors duration-200 sm:text-sm ${
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
                  <span className="ui-mono hidden tracking-[0.04em] sm:inline">
                    Trace {traceEnabled ? "ON" : "OFF"}
                  </span>
                </button>
              </>
            ) : null}
          </div>
        </div>
        <nav
          className="flex min-w-0 flex-wrap items-center gap-2 text-sm"
          aria-label="Primary"
        >
          {NAV_ITEMS.map((item) => {
            const active = isActivePath(pathname, item.href, item.exact);
            const href = item.href === "/sessions" ? sessionsHref : item.href;
            return (
              <Link
                key={item.href}
                href={href}
                className={navLinkClass(active)}
                aria-current={active ? "page" : undefined}
                style={
                  active
                    ? {
                        borderColor: "var(--accent-strong)",
                        backgroundColor: "var(--accent-soft)",
                        color: "var(--accent-strong)",
                      }
                    : {
                        color: "var(--muted)",
                      }
                }
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
