"use client";

import type { ReactNode } from "react";

import { Navbar } from "@/components/layout/Navbar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <Navbar />
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
