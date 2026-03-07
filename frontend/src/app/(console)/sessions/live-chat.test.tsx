import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SessionsPage from "@/app/sessions/page";

const navigationState = vi.hoisted(() => ({
  pathname: "/sessions",
  searchParams: new URLSearchParams("agent=default&scope=active&session=s-1"),
  replace: vi.fn((href: string) => {
    const url = new URL(href, "http://localhost");
    navigationState.searchParams = new URLSearchParams(url.search);
  }),
  push: vi.fn(),
}));

const storeState = vi.hoisted(() => ({
  currentAgentId: "default",
  currentSessionId: null as string | null,
  sessionsScope: "active" as "active" | "archived",
  messages: [] as Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    timestampMs: number | null;
    toolCalls: [];
    retrievals: [];
    debugEvents: [];
  }>,
  isStreaming: false,
  error: null as string | null,
  maxStepsPrompt: null,
}));

const {
  mockGetAgents,
  mockGetSessions,
  mockGetSessionHistory,
  mockSendMessage,
  mockSelectSession,
  mockSetCurrentAgent,
  mockSetSessionsScope,
  mockContinueAfterMaxSteps,
  mockCancelAfterMaxSteps,
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
  ]),
  mockGetSessions: vi.fn(async () => [
    {
      session_id: "s-1",
      title: "Alpha discussion",
      created_at: 1710000000,
      updated_at: 1710000001,
    },
  ]),
  mockGetSessionHistory: vi.fn(async () => ({
    session_id: "s-1",
    agent_id: "default",
    messages: [],
  })),
  mockSendMessage: vi.fn(async (content: string) => {
    storeState.messages = [
      ...storeState.messages,
      {
        id: `user-${storeState.messages.length}`,
        role: "user",
        content,
        timestampMs: 1_710_000_000_000,
        toolCalls: [],
        retrievals: [],
        debugEvents: [],
      },
      {
        id: `assistant-${storeState.messages.length}`,
        role: "assistant",
        content: `echo:${content}`,
        timestampMs: 1_710_000_000_100,
        toolCalls: [],
        retrievals: [],
        debugEvents: [],
      },
    ];
    return true;
  }),
  mockSelectSession: vi.fn(async (sessionId: string) => {
    storeState.currentSessionId = sessionId;
    storeState.sessionsScope = "active";
    storeState.messages = [
      {
        id: "assistant-seed",
        role: "assistant",
        content: "Live session ready",
        timestampMs: 1_710_000_000_000,
        toolCalls: [],
        retrievals: [],
        debugEvents: [],
      },
    ];
  }),
  mockSetCurrentAgent: vi.fn(async (agentId: string) => {
    storeState.currentAgentId = agentId;
    storeState.sessionsScope = "active";
  }),
  mockSetSessionsScope: vi.fn(async (scope: "active" | "archived") => {
    storeState.sessionsScope = scope;
  }),
  mockContinueAfterMaxSteps: vi.fn(async () => true),
  mockCancelAfterMaxSteps: vi.fn(async () => undefined),
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
  getSessions: mockGetSessions,
  getSessionHistory: mockGetSessionHistory,
  createSession: vi.fn(),
  archiveSession: vi.fn(),
  restoreSession: vi.fn(),
  deleteSession: vi.fn(),
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => ({
    ...storeState,
    sendMessage: mockSendMessage,
    selectSession: mockSelectSession,
    setCurrentAgent: mockSetCurrentAgent,
    setSessionsScope: mockSetSessionsScope,
    continueAfterMaxSteps: mockContinueAfterMaxSteps,
    cancelAfterMaxSteps: mockCancelAfterMaxSteps,
    openSessionInWorkspace: vi.fn(),
  }),
}));

describe("SessionsPage live chat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigationState.searchParams = new URLSearchParams(
      "agent=default&scope=active&session=s-1",
    );
    storeState.currentAgentId = "default";
    storeState.currentSessionId = null;
    storeState.sessionsScope = "active";
    storeState.messages = [];
    storeState.isStreaming = false;
    storeState.error = null;
    storeState.maxStepsPrompt = null;
  });

  it("uses the selected active session as the live chat surface", async () => {
    const { rerender } = render(<SessionsPage />);

    await waitFor(() => expect(mockSelectSession).toHaveBeenCalledWith("s-1"));
    rerender(<SessionsPage />);

    expect(screen.getAllByText("Live session ready").length).toBeGreaterThan(0);

    fireEvent.change(screen.getAllByLabelText("Chat message")[0], {
      target: { value: "Hello operator" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Send" })[0]);

    await waitFor(() =>
      expect(mockSendMessage).toHaveBeenCalledWith("Hello operator"),
    );
  });
});
