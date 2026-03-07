"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { InspectorPanel } from "@/components/editor/InspectorPanel";
import { ResizeHandle } from "@/components/layout/ResizeHandle";
import { Sidebar } from "@/components/layout/Sidebar";
import { TabButton, TabsList } from "@/components/ui/primitives";

type MobilePanel = "sidebar" | "inspector";

const LAYOUT_KEY = "mini-openclaw:agents-layout:v1";
const DEFAULT_LEFT = 320;
const MIN_LEFT = 280;
const MIN_MAIN = 720;
const RESIZE_STEP = 32;

function clampLeft(left: number, width: number) {
  const maxLeft = Math.max(MIN_LEFT, width - MIN_MAIN - 8);
  return Math.min(maxLeft, Math.max(MIN_LEFT, left));
}

export default function Home() {
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("inspector");
  const [leftWidth, setLeftWidth] = useState(DEFAULT_LEFT);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(LAYOUT_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        left?: number;
        leftCollapsed?: boolean;
      };
      const left = Number(parsed.left);
      if (Number.isFinite(left)) {
        setLeftWidth(left);
      }
      setLeftCollapsed(Boolean(parsed.leftCollapsed));
    } catch {
      // ignore malformed localStorage payload
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      LAYOUT_KEY,
      JSON.stringify({ left: leftWidth, leftCollapsed }),
    );
  }, [leftCollapsed, leftWidth]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || !event.shiftKey) return;
      if (event.key.toLowerCase() !== "[") return;
      event.preventDefault();
      setLeftCollapsed((previous) => !previous);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  function getContainerWidth(fallback = leftWidth) {
    const host = containerRef.current;
    if (host) {
      return host.getBoundingClientRect().width;
    }
    return fallback + MIN_MAIN + 8;
  }

  function startResize(startX: number) {
    const host = containerRef.current;
    if (!host) return;
    const startLeft = leftWidth;
    setDragging(true);

    const handleMove = (event: PointerEvent) => {
      const delta = event.clientX - startX;
      const width = host.getBoundingClientRect().width;
      setLeftWidth(clampLeft(startLeft + delta, width));
    };

    const handleUp = () => {
      setDragging(false);
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  }

  function stepResize(direction: -1 | 1) {
    setLeftWidth((previous) => {
      const width = getContainerWidth(previous);
      return clampLeft(previous + direction * RESIZE_STEP, width);
    });
  }

  const desktopTemplateColumns = useMemo(() => {
    if (leftCollapsed) {
      return "minmax(0,1fr)";
    }
    return `${leftWidth}px 10px minmax(0,1fr)`;
  }, [leftCollapsed, leftWidth]);

  const containerWidth = getContainerWidth();
  const leftMax = Math.max(MIN_LEFT, containerWidth - MIN_MAIN - 8);

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
            onClick={() => setLeftCollapsed((previous) => !previous)}
            aria-pressed={leftCollapsed}
            aria-label={leftCollapsed ? "Show agent console" : "Hide agent console"}
          >
            {leftCollapsed ? "Show Console" : "Hide Console"}
          </button>
          <button
            type="button"
            className="ui-btn ui-btn-sm ui-btn-ghost"
            onClick={() => {
              setLeftCollapsed(false);
              setLeftWidth(DEFAULT_LEFT);
            }}
          >
            Reset Layout
          </button>
        </div>

        <section
          ref={containerRef}
          className="grid min-h-0 min-w-0 flex-1 gap-0"
          style={{ gridTemplateColumns: desktopTemplateColumns }}
        >
          {!leftCollapsed ? <Sidebar /> : null}
          {!leftCollapsed ? (
            <ResizeHandle
              dragging={dragging}
              valueNow={leftWidth}
              valueMin={MIN_LEFT}
              valueMax={leftMax}
              onStep={stepResize}
              onPointerDown={(event) => {
                event.preventDefault();
                startResize(event.clientX);
              }}
            />
          ) : null}
          <InspectorPanel />
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
          id="mobile-panel-inspector"
          role="tabpanel"
          aria-labelledby="mobile-tab-inspector"
          hidden={mobilePanel !== "inspector"}
          className="h-full"
        >
          <InspectorPanel />
        </div>
      </section>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-[var(--border)] bg-[var(--surface-2)]/95 p-2 backdrop-blur md:hidden">
        <TabsList
          className="grid grid-cols-2"
          ariaLabel="Workspace panels"
          value={mobilePanel}
          onChange={(value) => setMobilePanel(value as MobilePanel)}
        >
          <TabButton
            id="mobile-tab-sessions"
            controls="mobile-panel-sessions"
            value="sidebar"
          >
            Console
          </TabButton>
          <TabButton
            id="mobile-tab-inspector"
            controls="mobile-panel-inspector"
            value="inspector"
          >
            Inspector
          </TabButton>
        </TabsList>
      </div>
    </main>
  );
}
