import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { ChatPanel } from "@/components/chat/ChatPanel";

const mockStore = vi.hoisted(() => ({
  messages: [] as Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    timestampMs: number | null;
    toolCalls: Array<{ tool: string; input?: unknown; output?: unknown }>;
    selectedSkills: string[];
    skillUses: string[];
    retrievals: Array<unknown>;
    debugEvents: Array<unknown>;
  }>,
  error: null as string | null,
  isStreaming: false,
  sessionsScope: "active" as "active" | "archived",
  maxStepsPrompt: null,
  delegates: [] as Array<{
    delegate_id: string;
    role: string;
    task: string;
    status: "running" | "completed" | "failed" | "timeout";
    sub_session_id: string;
    created_at: number;
    detail?: {
      delegate_id: string;
      role: string;
      task: string;
      status: "running" | "completed" | "failed" | "timeout";
      sub_session_id: string;
      created_at: number;
      agent_id: string;
      parent_session_id: string;
      allowed_tools: string[];
      result_summary?: string;
      steps_completed?: number;
      tools_used?: string[];
      duration_ms?: number;
      error_message?: string;
      result_file?: string;
    };
  }>,
  continueAfterMaxSteps: vi.fn(async () => undefined),
  cancelAfterMaxSteps: vi.fn(async () => undefined),
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => mockStore,
}));

vi.mock("@/components/chat/ChatInput", () => ({
  ChatInput: () => <div>chat-input</div>,
}));

vi.mock("@/components/chat/ChatMessage", () => ({
  ChatMessage: ({ content }: { content: string }) => <div>{content}</div>,
}));

function setScrollMetrics(
  element: HTMLDivElement,
  metrics: { scrollTop: number; clientHeight: number; scrollHeight: number },
) {
  Object.defineProperty(element, "scrollTop", {
    value: metrics.scrollTop,
    writable: true,
    configurable: true,
  });
  Object.defineProperty(element, "clientHeight", {
    value: metrics.clientHeight,
    configurable: true,
  });
  Object.defineProperty(element, "scrollHeight", {
    value: metrics.scrollHeight,
    configurable: true,
  });
}

describe("ChatPanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockStore.messages = [
      {
        id: "m1",
        role: "assistant",
        content: "first",
        timestampMs: 0,
        toolCalls: [],
        selectedSkills: ["weather_helper"],
        skillUses: ["get_weather"],
        retrievals: [],
        debugEvents: [],
      },
    ];
    mockStore.error = null;
    mockStore.isStreaming = false;
    mockStore.sessionsScope = "active";
    mockStore.maxStepsPrompt = null;
    mockStore.delegates = [];
  });

  it("keeps the reader position when they are away from the live edge", () => {
    const { container, rerender } = render(<ChatPanel />);
    const scrollArea = container.querySelector(".ui-scroll-area");

    if (!(scrollArea instanceof HTMLDivElement)) {
      throw new Error("scroll area not found");
    }

    setScrollMetrics(scrollArea, {
      scrollTop: 40,
      clientHeight: 200,
      scrollHeight: 600,
    });
    fireEvent.scroll(scrollArea);

    mockStore.messages = [
      ...mockStore.messages,
      {
        id: "m2",
        role: "assistant",
        content: "second",
        timestampMs: 1,
        toolCalls: [],
        selectedSkills: [],
        skillUses: [],
        retrievals: [],
        debugEvents: [],
      },
    ];
    setScrollMetrics(scrollArea, {
      scrollTop: 40,
      clientHeight: 200,
      scrollHeight: 900,
    });

    rerender(<ChatPanel />);

    expect(scrollArea.scrollTop).toBe(40);
    expect(
      screen.getByRole("button", { name: "Jump to latest" }),
    ).toBeInTheDocument();
  });

  it("sticks to the latest message while the user remains near the live edge", () => {
    const { container, rerender } = render(<ChatPanel />);
    const scrollArea = container.querySelector(".ui-scroll-area");

    if (!(scrollArea instanceof HTMLDivElement)) {
      throw new Error("scroll area not found");
    }

    setScrollMetrics(scrollArea, {
      scrollTop: 390,
      clientHeight: 200,
      scrollHeight: 600,
    });
    fireEvent.scroll(scrollArea);

    mockStore.messages = [
      ...mockStore.messages,
      {
        id: "m2",
        role: "assistant",
        content: "second",
        timestampMs: 1,
        toolCalls: [],
        selectedSkills: [],
        skillUses: [],
        retrievals: [],
        debugEvents: [],
      },
    ];
    setScrollMetrics(scrollArea, {
      scrollTop: 390,
      clientHeight: 200,
      scrollHeight: 900,
    });

    rerender(<ChatPanel />);

    expect(scrollArea.scrollTop).toBe(900);
    expect(
      screen.queryByRole("button", { name: "Jump to latest" }),
    ).not.toBeInTheDocument();
  });

  it("shows session tool and skill summary badges", () => {
    mockStore.messages = [
      {
        id: "m1",
        role: "assistant",
        content: "first",
        timestampMs: 0,
        toolCalls: [{ tool: "read_files" }],
        selectedSkills: ["weather_helper"],
        skillUses: ["get_weather"],
        retrievals: [],
        debugEvents: [],
      },
    ];

    render(<ChatPanel />);

    expect(screen.getByText("Tools Used")).toBeInTheDocument();
    expect(screen.getByText("Skills Selected")).toBeInTheDocument();
    expect(screen.getByText("Skills Used")).toBeInTheDocument();
    expect(screen.getByText("read_files (1)")).toBeInTheDocument();
    expect(screen.getByText("weather_helper (1)")).toBeInTheDocument();
    expect(screen.getByText("get_weather (1)")).toBeInTheDocument();
  });

  it("renders a terminal delegate result card when detail is available", () => {
    mockStore.delegates = [
      {
        delegate_id: "del_done",
        role: "researcher",
        task: "Summarize memory",
        status: "completed",
        sub_session_id: "sub_done",
        created_at: 1,
        detail: {
          delegate_id: "del_done",
          role: "researcher",
          task: "Summarize memory",
          status: "completed",
          sub_session_id: "sub_done",
          created_at: 1,
          agent_id: "default",
          parent_session_id: "sess_1",
          allowed_tools: ["read_files"],
          result_summary: "Delegate finished successfully.",
          steps_completed: 2,
          tools_used: ["read_files"],
          duration_ms: 1200,
        },
      },
    ];

    render(<ChatPanel />);

    expect(screen.getByText("Delegated Tasks")).toBeInTheDocument();
    expect(screen.getByTestId("delegate-result-card")).toBeInTheDocument();
  });

  it("shows timeout detail text for terminal delegate failures", () => {
    mockStore.delegates = [
      {
        delegate_id: "del_timeout",
        role: "researcher",
        task: "Summarize memory",
        status: "timeout",
        sub_session_id: "sub_timeout",
        created_at: 1,
        detail: {
          delegate_id: "del_timeout",
          role: "researcher",
          task: "Summarize memory",
          status: "timeout",
          sub_session_id: "sub_timeout",
          created_at: 1,
          agent_id: "default",
          parent_session_id: "sess_1",
          allowed_tools: ["read_files"],
          error_message: "Sub-agent exceeded timeout (60s)",
          result_file: "/tmp/result_summary.md",
        },
      },
    ];

    render(<ChatPanel />);

    expect(screen.getByText("Sub-agent exceeded timeout (60s)")).toBeInTheDocument();
    expect(screen.getByTestId("delegate-result-card")).toBeInTheDocument();
  });
});
