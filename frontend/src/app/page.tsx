"use client";

import { useEffect, useRef, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { InspectorPanel } from "@/components/editor/InspectorPanel";
import { Navbar } from "@/components/layout/Navbar";
import { ResizeHandle } from "@/components/layout/ResizeHandle";
import { Sidebar } from "@/components/layout/Sidebar";
import { TabButton, TabsList } from "@/components/ui/primitives";

type MobilePanel = "sidebar" | "chat" | "inspector";
type DragTarget = "left" | "right" | null;

const LAYOUT_KEY = "mini-openclaw:layout:v1";
const DEFAULT_LAYOUT = { left: 300, right: 360 };
const MIN_LEFT = 260;
const MIN_RIGHT = 340;
const MIN_CENTER = 420;

export default function Home() {
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");
  const [layout, setLayout] = useState(DEFAULT_LAYOUT);
  const [dragging, setDragging] = useState<DragTarget>(null);
  const containerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(LAYOUT_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as { left?: number; right?: number };
      const left = Number(parsed.left);
      const right = Number(parsed.right);
      if (!Number.isFinite(left) || !Number.isFinite(right)) return;
      setLayout({ left, right });
    } catch {
      // ignore malformed localStorage payload
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  }, [layout]);

  function startResize(target: Exclude<DragTarget, null>, startX: number) {
    const host = containerRef.current;
    if (!host) return;
    const startLeft = layout.left;
    const startRight = layout.right;
    setDragging(target);

    const handleMove = (event: PointerEvent) => {
      const delta = event.clientX - startX;
      const width = host.getBoundingClientRect().width;
      if (target === "left") {
        const maxLeft = Math.max(
          MIN_LEFT,
          width - startRight - MIN_CENTER - 16,
        );
        const nextLeft = Math.min(
          maxLeft,
          Math.max(MIN_LEFT, startLeft + delta),
        );
        setLayout((prev) => ({ ...prev, left: nextLeft }));
        return;
      }
      const maxRight = Math.max(MIN_RIGHT, width - startLeft - MIN_CENTER - 16);
      const nextRight = Math.min(
        maxRight,
        Math.max(MIN_RIGHT, startRight - delta),
      );
      setLayout((prev) => ({ ...prev, right: nextRight }));
    };

    const handleUp = () => {
      setDragging(null);
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  }

  return (
    <main
      id="main-content"
      className="app-main flex h-screen flex-col overflow-hidden"
    >
      <Navbar />

      <section
        ref={containerRef}
        className="hidden h-full min-w-0 gap-0 p-3 md:grid"
        style={{
          gridTemplateColumns: `${layout.left}px 10px minmax(0,1fr) 10px ${layout.right}px`,
        }}
      >
        <Sidebar />
        <ResizeHandle
          dragging={dragging === "left"}
          onPointerDown={(event) => {
            event.preventDefault();
            startResize("left", event.clientX);
          }}
        />
        <ChatPanel />
        <ResizeHandle
          dragging={dragging === "right"}
          onPointerDown={(event) => {
            event.preventDefault();
            startResize("right", event.clientX);
          }}
        />
        <InspectorPanel />
      </section>

      <section className="h-full min-w-0 p-3 pb-24 md:hidden">
        <div
          id="mobile-panel-sessions"
          role="tabpanel"
          aria-labelledby="mobile-tab-sessions"
          hidden={mobilePanel !== "sidebar"}
          className="h-full"
        >
          <Sidebar />
        </div>
        <div
          id="mobile-panel-chat"
          role="tabpanel"
          aria-labelledby="mobile-tab-chat"
          hidden={mobilePanel !== "chat"}
          className="h-full"
        >
          <ChatPanel />
        </div>
        <div
          id="mobile-panel-inspector"
          role="tabpanel"
          aria-labelledby="mobile-tab-inspector"
          hidden={mobilePanel !== "inspector"}
          className="h-full"
        >
          <InspectorPanel />
        </div>
      </section>

      <TabsList
        className="mobile-tabs md:hidden"
        ariaLabel="Workspace panels"
        value={mobilePanel}
        onChange={(value) => setMobilePanel(value as MobilePanel)}
      >
        <TabButton
          id="mobile-tab-sessions"
          controls="mobile-panel-sessions"
          value="sidebar"
        >
          Sessions
        </TabButton>
        <TabButton
          id="mobile-tab-chat"
          controls="mobile-panel-chat"
          value="chat"
        >
          Chat
        </TabButton>
        <TabButton
          id="mobile-tab-inspector"
          controls="mobile-panel-inspector"
          value="inspector"
        >
          Inspector
        </TabButton>
      </TabsList>
    </main>
  );
}
