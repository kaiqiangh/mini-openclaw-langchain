"use client";

import { useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { InspectorPanel } from "@/components/editor/InspectorPanel";
import { Navbar } from "@/components/layout/Navbar";
import { ResizeHandle } from "@/components/layout/ResizeHandle";
import { Sidebar } from "@/components/layout/Sidebar";

type MobilePanel = "sidebar" | "chat" | "inspector";

export default function Home() {
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");

  return (
    <main className="flex h-screen flex-col overflow-hidden">
      <Navbar />

      <div className="mobile-tabs md:hidden">
        <button
          className={mobilePanel === "sidebar" ? "active" : ""}
          onClick={() => setMobilePanel("sidebar")}
        >
          Sessions
        </button>
        <button
          className={mobilePanel === "chat" ? "active" : ""}
          onClick={() => setMobilePanel("chat")}
        >
          Chat
        </button>
        <button
          className={mobilePanel === "inspector" ? "active" : ""}
          onClick={() => setMobilePanel("inspector")}
        >
          Inspector
        </button>
      </div>

      <section className="hidden h-full grid-cols-[280px_8px_1fr_8px_360px] gap-0 p-3 md:grid">
        <Sidebar />
        <ResizeHandle />
        <ChatPanel />
        <ResizeHandle />
        <InspectorPanel />
      </section>

      <section className="h-full p-3 md:hidden">
        {mobilePanel === "sidebar" ? <Sidebar /> : null}
        {mobilePanel === "chat" ? <ChatPanel /> : null}
        {mobilePanel === "inspector" ? <InspectorPanel /> : null}
      </section>
    </main>
  );
}
