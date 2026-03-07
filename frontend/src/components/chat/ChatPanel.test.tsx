import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { ChatPanel } from "@/components/chat/ChatPanel";

const mockStore = vi.hoisted(() => ({
  messages: [] as Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    timestampMs: number | null;
    toolCalls: [];
    retrievals: [];
    debugEvents: [];
  }>,
  error: null as string | null,
  isStreaming: false,
  sessionsScope: "active" as "active" | "archived",
  maxStepsPrompt: null,
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
        retrievals: [],
        debugEvents: [],
      },
    ];
    mockStore.error = null;
    mockStore.isStreaming = false;
    mockStore.sessionsScope = "active";
    mockStore.maxStepsPrompt = null;
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
});
