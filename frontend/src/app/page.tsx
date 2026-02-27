"use client";

import { useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { InspectorPanel } from "@/components/editor/InspectorPanel";
import { Navbar } from "@/components/layout/Navbar";
import { ResizeHandle } from "@/components/layout/ResizeHandle";
import { Sidebar } from "@/components/layout/Sidebar";
import { TabButton, TabsList } from "@/components/ui/primitives";

type MobilePanel = "sidebar" | "chat" | "inspector";

export default function Home() {
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");

  return (
    <main id="main-content" className="app-main flex h-screen flex-col overflow-hidden">
      <Navbar />

      <TabsList className="mobile-tabs md:hidden">
        <TabButton
          type="button"
          active={mobilePanel === "sidebar"}
          onClick={() => setMobilePanel("sidebar")}
        >
          Sessions
        </TabButton>
        <TabButton
          type="button"
          active={mobilePanel === "chat"}
          onClick={() => setMobilePanel("chat")}
        >
          Chat
        </TabButton>
        <TabButton
          type="button"
          active={mobilePanel === "inspector"}
          onClick={() => setMobilePanel("inspector")}
        >
          Inspector
        </TabButton>
      </TabsList>

      <section className="hidden h-full grid-cols-[280px_8px_minmax(0,1fr)_8px_360px] gap-0 p-3 md:grid">
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
