"use client";

import { useEffect, useState } from "react";
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
  return `inline-flex min-h-[42px] items-center rounded-full border px-4 py-2 text-sm font-semibold transition-all duration-200 ${
    active
      ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)] shadow-[inset_0_1px_0_rgba(255,255,255,0.25)]"
      : "border-[var(--border)] bg-[var(--surface-3)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]"
  }`;
}

export function Navbar() {
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
    <header className="z-20 border-b border-[var(--border)] bg-[var(--bg)]/86 backdrop-blur-xl">
      <div className="px-3 py-3 sm:px-4">
        <div className="panel-shell overflow-visible px-4 py-4 sm:px-5">
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-[var(--border)] bg-[var(--surface-3)] px-3 py-1 font-[var(--font-mono)] text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
                    Editorial control room
                  </span>
                  <Badge tone={runtimeTone}>{runtimeLabel}</Badge>
                  <Badge
                    tone="neutral"
                    className="max-w-[220px] truncate"
                  >
                    Agent: {currentAgentId}
                  </Badge>
                </div>
                <div className="flex flex-wrap items-end gap-4">
                  <div className="min-w-0">
                    <div className="font-[var(--font-display)] text-[clamp(1.6rem,1.2rem+1vw,2.35rem)] leading-[0.92] tracking-[-0.05em] text-[var(--text-strong)]">
                      mini OpenClaw
                    </div>
                    <div className="mt-1 max-w-[52rem] text-sm text-[var(--muted)] sm:text-[0.95rem]">
                      Local-first agent workspace for live sessions, scheduled
                      runs, and operator visibility.
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
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
                          className={`group inline-flex min-h-[42px] items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition-all duration-200 ${
                            ragEnabled
                              ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                              : "border-[var(--border)] bg-[var(--surface-3)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--text)]"
                          } ${isStreaming ? "cursor-not-allowed opacity-60" : ""}`}
                        >
                          <span
                            aria-hidden
                            className={`inline-flex h-6 w-6 items-center justify-center rounded-full border ${
                              ragEnabled
                                ? "border-[var(--accent-strong)] bg-[var(--surface-3)]"
                                : "border-[var(--border-strong)] bg-[var(--surface-2)]"
                            }`}
                          >
                            <svg
                              viewBox="0 0 20 20"
                              className="h-3.5 w-3.5"
                              fill="none"
                            >
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
                          className={`group inline-flex min-h-[42px] items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition-all duration-200 ${
                            traceEnabled
                              ? "border-[var(--accent-strong)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                              : "border-[var(--border)] bg-[var(--surface-3)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--text)]"
                          } ${traceLoading ? "cursor-not-allowed opacity-60" : ""}`}
                        >
                          <span
                            aria-hidden
                            className={`inline-flex h-6 w-6 items-center justify-center rounded-full border ${
                              traceEnabled
                                ? "border-[var(--accent-strong)] bg-[var(--surface-3)]"
                                : "border-[var(--border-strong)] bg-[var(--surface-2)]"
                            }`}
                          >
                            <svg
                              viewBox="0 0 20 20"
                              className="h-3.5 w-3.5"
                              fill="none"
                            >
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
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-soft)]">
                Views
              </span>
              <nav
                className="flex min-w-0 flex-1 flex-wrap items-center gap-2 overflow-x-auto pb-1"
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
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </nav>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3 text-xs text-[var(--muted)]">
              <span className="font-medium text-[var(--text)]">
                Runtime state:
              </span>
              <span>{runtimeLabel}</span>
              {currentSessionId ? (
                <>
                  <span aria-hidden>·</span>
                  <span className="ui-mono truncate">
                    Session {currentSessionId}
                  </span>
                </>
              ) : null}
              {sessionsScope === "archived" ? (
                <>
                  <span aria-hidden>·</span>
                  <span>Viewing archived inbox</span>
                </>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
