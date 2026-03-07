"use client";

import type { ReactNode } from "react";

import { Navbar } from "@/components/layout/Navbar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-dvh min-h-dvh flex-col overflow-hidden">
      <Navbar />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  );
}
