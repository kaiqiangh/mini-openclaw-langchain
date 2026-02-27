"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAppStore } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";

export function Navbar() {
  const { ragEnabled, toggleRag, isStreaming, currentAgentId } = useAppStore();
  const pathname = usePathname();

  const workspaceActive = pathname === "/";
  const usageActive = pathname?.startsWith("/usage");

  return (
    <header className="z-20 flex h-14 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-2)] px-4 backdrop-blur-md">
      <div className="flex min-w-0 items-center gap-3">
        <div className="min-w-0 text-sm font-semibold tracking-[0.06em] text-[var(--text)]">mini OpenClaw</div>
        <Badge tone="neutral" className="max-w-[220px] truncate">
          Agent: {currentAgentId}
        </Badge>
        {isStreaming ? <Badge tone="accent">Running</Badge> : <Badge tone="success">Idle</Badge>}
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
        </nav>
      </div>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
          <span>RAG</span>
          <input
            type="checkbox"
            name="rag-enabled"
            aria-label="Enable retrieval augmented generation"
            className="h-4 w-4 rounded border-[var(--border-strong)] bg-[var(--surface-3)] text-[var(--accent)]"
            checked={ragEnabled}
            disabled={isStreaming}
            onChange={(event) => {
              void toggleRag(event.target.checked);
            }}
          />
        </label>
      </div>
    </header>
  );
}
