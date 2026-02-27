"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAppStore } from "@/lib/store";

export function Navbar() {
  const { ragEnabled, toggleRag, isStreaming, currentAgentId } = useAppStore();
  const pathname = usePathname();

  return (
    <header className="flex h-14 items-center justify-between border-b border-gray-200 bg-white/70 px-4 backdrop-blur-md">
      <div className="flex items-center gap-4">
        <div className="text-sm font-semibold">mini OpenClaw</div>
        <div className="rounded bg-gray-100 px-2 py-1 text-[11px] text-gray-600">Agent: {currentAgentId}</div>
        <nav className="flex items-center gap-2 text-xs">
          <Link
            href="/"
            className={`rounded px-2 py-1 ${pathname === "/" ? "bg-blue-100 text-blue-700" : "text-gray-600"}`}
          >
            Workspace
          </Link>
          <Link
            href="/usage"
            className={`rounded px-2 py-1 ${
              pathname?.startsWith("/usage") ? "bg-blue-100 text-blue-700" : "text-gray-600"
            }`}
          >
            Usage
          </Link>
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-xs text-gray-600">
          <span>RAG</span>
          <input
            type="checkbox"
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
