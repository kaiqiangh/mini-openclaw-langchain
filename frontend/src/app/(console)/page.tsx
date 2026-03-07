"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { InspectorPanel } from "@/components/editor/InspectorPanel";
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
const RESIZE_STEP = 32;

function clampLeft(left: number, width: number, right: number) {
  const maxLeft = Math.max(MIN_LEFT, width - right - MIN_CENTER - 16);
  return Math.min(maxLeft, Math.max(MIN_LEFT, left));
}

function clampRight(right: number, width: number, left: number) {
  const maxRight = Math.max(MIN_RIGHT, width - left - MIN_CENTER - 16);
  return Math.min(maxRight, Math.max(MIN_RIGHT, right));
}

export default function Home() {
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");
  const [layout, setLayout] = useState(DEFAULT_LAYOUT);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [dragging, setDragging] = useState<DragTarget>(null);
  const containerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(LAYOUT_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        left?: number;
        right?: number;
        leftCollapsed?: boolean;
        rightCollapsed?: boolean;
      };
      const left = Number(parsed.left);
      const right = Number(parsed.right);
      if (!Number.isFinite(left) || !Number.isFinite(right)) return;
      setLayout({ left, right });
      setLeftCollapsed(Boolean(parsed.leftCollapsed));
      setRightCollapsed(Boolean(parsed.rightCollapsed));
    } catch {
      // ignore malformed localStorage payload
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      LAYOUT_KEY,
      JSON.stringify({ ...layout, leftCollapsed, rightCollapsed }),
    );
  }, [layout, leftCollapsed, rightCollapsed]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || !event.shiftKey) return;
      if (event.key.toLowerCase() === "[") {
        event.preventDefault();
        setLeftCollapsed((prev) => !prev);
      }
      if (event.key.toLowerCase() === "]") {
        event.preventDefault();
        setRightCollapsed((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  function getContainerWidth(fallback = layout) {
    const host = containerRef.current;
    if (host) {
      return host.getBoundingClientRect().width;
    }
    return fallback.left + fallback.right + MIN_CENTER + 16;
  }

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
        const nextLeft = clampLeft(startLeft + delta, width, startRight);
        setLayout((prev) => ({ ...prev, left: nextLeft }));
        return;
      }
      const nextRight = clampRight(startRight - delta, width, startLeft);
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

  function stepResize(target: Exclude<DragTarget, null>, direction: -1 | 1) {
    setLayout((previous) => {
      const width = getContainerWidth(previous);
      if (target === "left") {
        return {
          ...previous,
          left: clampLeft(previous.left + direction * RESIZE_STEP, width, previous.right),
        };
      }
      return {
        ...previous,
        right: clampRight(
          previous.right - direction * RESIZE_STEP,
          width,
          previous.left,
        ),
      };
    });
  }

  const desktopTemplateColumns = useMemo(() => {
    const cols: string[] = [];
    if (!leftCollapsed) {
      cols.push(`${layout.left}px`);
      cols.push("10px");
    }
    cols.push("minmax(0,1fr)");
    if (!rightCollapsed) {
      cols.push("10px");
      cols.push(`${layout.right}px`);
    }
    return cols.join(" ");
  }, [layout.left, layout.right, leftCollapsed, rightCollapsed]);

  const containerWidth = getContainerWidth();
  const leftMax = Math.max(MIN_LEFT, containerWidth - layout.right - MIN_CENTER - 16);
  const rightMax = Math.max(MIN_RIGHT, containerWidth - layout.left - MIN_CENTER - 16);

  return (
    <main
      id="main-content"
      className="app-main flex min-h-0 flex-1 flex-col overflow-hidden"
    >
      <section className="hidden h-full min-w-0 p-3 md:flex md:flex-col">
        <div className="mb-2 flex items-center justify-end gap-2">
          <button
            type="button"
            className="ui-btn ui-btn-sm"
            onClick={() => setLeftCollapsed((prev) => !prev)}
            aria-pressed={leftCollapsed}
            aria-label={leftCollapsed ? "Show agent console" : "Hide agent console"}
          >
            {leftCollapsed ? "Show Console" : "Hide Console"}
          </button>
          <button
            type="button"
            className="ui-btn ui-btn-sm"
            onClick={() => setRightCollapsed((prev) => !prev)}
            aria-pressed={rightCollapsed}
            aria-label={rightCollapsed ? "Show inspector" : "Hide inspector"}
          >
            {rightCollapsed ? "Show Inspector" : "Hide Inspector"}
          </button>
          <button
            type="button"
            className="ui-btn ui-btn-sm ui-btn-ghost"
            onClick={() => {
              setLeftCollapsed(false);
              setRightCollapsed(false);
              setLayout(DEFAULT_LAYOUT);
            }}
          >
            Reset Layout
          </button>
        </div>
        <section
          ref={containerRef}
          className="grid min-h-0 flex-1 min-w-0 gap-0"
          style={{ gridTemplateColumns: desktopTemplateColumns }}
        >
          {!leftCollapsed ? <Sidebar /> : null}
          {!leftCollapsed ? (
            <ResizeHandle
              dragging={dragging === "left"}
              valueNow={layout.left}
              valueMin={MIN_LEFT}
              valueMax={leftMax}
              onStep={(direction) => stepResize("left", direction)}
              onPointerDown={(event) => {
                event.preventDefault();
                startResize("left", event.clientX);
              }}
            />
          ) : null}
          <ChatPanel />
          {!rightCollapsed ? (
            <ResizeHandle
              dragging={dragging === "right"}
              valueNow={layout.right}
              valueMin={MIN_RIGHT}
              valueMax={rightMax}
              onStep={(direction) => stepResize("right", direction)}
              onPointerDown={(event) => {
                event.preventDefault();
                startResize("right", event.clientX);
              }}
            />
          ) : null}
          {!rightCollapsed ? <InspectorPanel /> : null}
        </section>
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
