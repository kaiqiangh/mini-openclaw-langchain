import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import TracesPage from "@/app/traces/page";

const navigationState = vi.hoisted(() => ({
  pathname: "/traces",
  searchParams: new URLSearchParams(),
  replace: vi.fn((href: string) => {
    const url = new URL(href, "http://localhost");
    navigationState.searchParams = new URLSearchParams(url.search);
  }),
  push: vi.fn((href: string) => {
    const url = new URL(href, "http://localhost");
    navigationState.searchParams = new URLSearchParams(url.search);
  }),
}));

const {
  mockGetAgents,
  mockListTraceEvents,
  mockGetTraceEvent,
} = vi.hoisted(() => ({
  mockGetAgents: vi.fn(async () => [
    {
      agent_id: "default",
      path: "/tmp/default",
      created_at: 0,
      updated_at: 0,
      active_sessions: 1,
      archived_sessions: 0,
    },
    {
      agent_id: "alpha",
      path: "/tmp/alpha",
      created_at: 0,
      updated_at: 0,
      active_sessions: 1,
      archived_sessions: 0,
    },
  ]),
  mockListTraceEvents: vi.fn(async () => ({
    agent_id: "alpha",
    total: 2,
    next_cursor: null,
    summary: {
      total_matches: 2,
      by_event: {
        tool_end: 1,
        llm_error: 1,
      },
    },
    events: [
      {
        event_id: "trace-2",
        timestamp_ms: 1_710_000_001_000,
        agent_id: "alpha",
        run_id: "run-2",
        session_id: "session-2",
        trigger_type: "chat",
        event: "llm_error",
        summary: "provider timeout",
        details: { error: "provider timeout" },
        source: "runs.events",
      },
      {
        event_id: "trace-1",
        timestamp_ms: 1_710_000_000_000,
        agent_id: "alpha",
        run_id: "run-1",
        session_id: "session-1",
        trigger_type: "chat",
        event: "tool_end",
        summary: "read_files completed",
        details: { tool: "read_files", output: "ok" },
        source: "audit.steps",
      },
    ],
  })),
  mockGetTraceEvent: vi.fn(async (traceId: string) =>
    traceId === "trace-1"
      ? {
          event_id: "trace-1",
          timestamp_ms: 1_710_000_000_000,
          agent_id: "alpha",
          run_id: "run-1",
          session_id: "session-1",
          trigger_type: "chat",
          event: "tool_end",
          summary: "read_files completed",
          details: { tool: "read_files", output: "ok" },
          source: "audit.steps",
        }
      : {
          event_id: "trace-2",
          timestamp_ms: 1_710_000_001_000,
          agent_id: "alpha",
          run_id: "run-2",
          session_id: "session-2",
          trigger_type: "chat",
          event: "llm_error",
          summary: "provider timeout",
          details: { error: "provider timeout" },
          source: "runs.events",
        },
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useSearchParams: () => navigationState.searchParams,
  useRouter: () => ({
    replace: navigationState.replace,
    push: navigationState.push,
  }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  getAgents: mockGetAgents,
  listTraceEvents: mockListTraceEvents,
  getTraceEvent: mockGetTraceEvent,
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => ({
    currentAgentId: "default",
  }),
}));

describe("TracesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigationState.searchParams = new URLSearchParams(
      "agent=alpha&window=7d&event=llm_error&trigger=chat&run=run-2&session=session-2&q=timeout&trace=trace-2",
    );
  });

  it("restores filters and selected trace detail from the URL and updates selection", async () => {
    const { rerender } = render(<TracesPage />);

    await waitFor(() =>
      expect(mockListTraceEvents).toHaveBeenCalledWith(
        expect.objectContaining({
          agentId: "alpha",
          window: "7d",
          event: "llm_error",
          trigger: "chat",
          runId: "run-2",
          sessionId: "session-2",
          query: "timeout",
        }),
      ),
    );
    await waitFor(() => expect(mockGetTraceEvent).toHaveBeenCalledWith("trace-2", "alpha"));

    expect(screen.getByLabelText("Filter traces by agent")).toHaveValue("alpha");
    expect(screen.getByLabelText("Filter traces by time window")).toHaveValue("7d");
    expect(screen.getByLabelText("Filter traces by event type")).toHaveValue("llm_error");
    expect(screen.getByLabelText("Filter traces by trigger")).toHaveValue("chat");
    expect(screen.getByDisplayValue("timeout")).toBeInTheDocument();

    const detail = screen.getAllByText("Trace Detail")[0].closest(".panel-shell");
    expect(detail).not.toBeNull();
    expect(within(detail as HTMLElement).getByText("provider timeout")).toBeInTheDocument();
    expect(screen.getByTestId("trace-page-main").className).toContain("overflow-hidden");
    expect(screen.getByTestId("trace-layout-grid").className).toContain("overflow-hidden");
    expect(screen.getByTestId("trace-timeline-scroll")).toBeInTheDocument();
    expect(screen.getByTestId("trace-detail-host").className).toContain("overflow-hidden");
    expect(screen.getByTestId("trace-detail-host").className).toContain("md:h-full");
    expect(
      within(detail as HTMLElement).getByRole("link", { name: "Open Run" }),
    ).toHaveAttribute("href", "/runs?agent=alpha&run=run-2");
    expect(
      within(detail as HTMLElement).getByRole("link", { name: "Open Session" }),
    ).toHaveAttribute("href", "/sessions?agent=alpha&session=session-2");

    fireEvent.click(screen.getByRole("button", { name: /trace-1/i }));
    expect(navigationState.push).toHaveBeenCalled();

    rerender(<TracesPage />);
    expect(navigationState.searchParams.get("trace")).toBe("trace-1");
    await waitFor(() => expect(mockGetTraceEvent).toHaveBeenCalledWith("trace-1", "alpha"));
    expect(within(detail as HTMLElement).getByText("read_files completed")).toBeInTheDocument();
  });
});
