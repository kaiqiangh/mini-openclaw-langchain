import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SessionsPage from "@/app/sessions/page";

type SessionRecord = {
  session_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  archived?: boolean;
};

const navigationState = vi.hoisted(() => ({
  pathname: "/sessions",
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

const storeState = vi.hoisted(() => ({
  currentAgentId: "default",
  currentSessionId: null as string | null,
  delegates: [] as Array<{
    delegate_id: string;
    role: string;
    task: string;
    status: "running" | "completed" | "failed" | "timeout";
    sub_session_id: string;
    created_at: number;
  }>,
  sessionsScope: "active" as "active" | "archived",
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
  isStreaming: false,
  error: null as string | null,
  maxStepsPrompt: null,
}));

let sessionFixtures: Record<
  string,
  { active: SessionRecord[]; archived: SessionRecord[] }
>;

function cloneSession(session: SessionRecord): SessionRecord {
  return { ...session };
}

function listAgents() {
  return Object.entries(sessionFixtures).map(([agentId, sessions]) => ({
    agent_id: agentId,
    path: `/tmp/${agentId}`,
    created_at: 0,
    updated_at: 0,
    active_sessions: sessions.active.length,
    archived_sessions: sessions.archived.length,
  }));
}

function readScope(
  agentId: string,
  scope: "active" | "archived" | "all",
): SessionRecord[] {
  const agent = sessionFixtures[agentId] ?? { active: [], archived: [] };
  if (scope === "active") {
    return agent.active.map(cloneSession);
  }
  if (scope === "archived") {
    return agent.archived.map((session) => ({ ...cloneSession(session), archived: true }));
  }
  return [
    ...agent.active.map(cloneSession),
    ...agent.archived.map((session) => ({ ...cloneSession(session), archived: true })),
  ];
}

const {
  mockGetAgents,
  mockGetSessions,
  mockGetSessionHistory,
  mockGetDelegateDetail,
  mockCreateSession,
  mockArchiveSession,
  mockRestoreSession,
  mockDeleteSession,
  mockSetCurrentAgent,
  mockSetSessionsScope,
  mockSelectSession,
  mockContinueAfterMaxSteps,
  mockCancelAfterMaxSteps,
} = vi.hoisted(() => ({
  mockGetAgents: vi.fn(async () => listAgents()),
  mockGetSessions: vi.fn(
    async (scope: "active" | "archived" | "all" = "active", agentId = "default") =>
      readScope(agentId, scope),
  ),
  mockGetSessionHistory: vi.fn(
    async (sessionId: string, archived = false, agentId = "default") => ({
      session_id: sessionId,
      agent_id: agentId,
      messages: [
        {
          role: "assistant" as const,
          content: `history:${agentId}:${archived ? "archived" : "active"}:${sessionId}`,
          timestamp_ms: 1_700_000_000_000,
          tool_calls: [],
          skill_uses: ["history_skill"],
        },
      ],
    }),
  ),
  mockGetDelegateDetail: vi.fn(async () => ({
    delegate_id: "del-1",
    agent_id: "default",
    parent_session_id: "s-1",
    role: "researcher",
    task: "Investigate flow",
    status: "completed",
    sub_session_id: "sub-1",
    created_at: 1_710_000_000_000,
    allowed_tools: ["web_search"],
    result_summary: "Found the issue.",
  })),
  mockCreateSession: vi.fn(async (_title?: string, agentId = "default") => {
    const created: SessionRecord = {
      session_id: "new-session",
      title: "New Session",
      created_at: 1710000100,
      updated_at: 1710000100,
    };
    sessionFixtures[agentId]?.active.unshift(created);
    return {
      session_id: created.session_id,
      title: created.title,
    };
  }),
  mockArchiveSession: vi.fn(async (sessionId: string, agentId = "default") => {
    const agent = sessionFixtures[agentId];
    if (!agent) return;
    const index = agent.active.findIndex((session) => session.session_id === sessionId);
    if (index < 0) return;
    const [target] = agent.active.splice(index, 1);
    agent.archived.unshift({ ...target, archived: true });
  }),
  mockRestoreSession: vi.fn(async (sessionId: string, agentId = "default") => {
    const agent = sessionFixtures[agentId];
    if (!agent) return;
    const index = agent.archived.findIndex(
      (session) => session.session_id === sessionId,
    );
    if (index < 0) return;
    const [target] = agent.archived.splice(index, 1);
    agent.active.unshift({ ...target, archived: false });
  }),
  mockDeleteSession: vi.fn(
    async (sessionId: string, archived = false, agentId = "default") => {
      const agent = sessionFixtures[agentId];
      if (!agent) return;
      const collection = archived ? agent.archived : agent.active;
      const index = collection.findIndex((session) => session.session_id === sessionId);
      if (index >= 0) {
        collection.splice(index, 1);
      }
    },
  ),
  mockSetCurrentAgent: vi.fn(async (agentId: string) => {
    storeState.currentAgentId = agentId;
    storeState.sessionsScope = "active";
  }),
  mockSetSessionsScope: vi.fn(async (scope: "active" | "archived") => {
    storeState.sessionsScope = scope;
  }),
  mockSelectSession: vi.fn(async (sessionId: string) => {
    storeState.currentSessionId = sessionId;
    storeState.sessionsScope = "active";
    storeState.messages = [
      {
        id: `assistant-${sessionId}`,
        role: "assistant",
        content: `live:${sessionId}`,
        timestampMs: 1_710_000_000_000,
        toolCalls: [{ tool: "read_files" }],
        selectedSkills: ["weather_helper"],
        skillUses: ["get_weather"],
        retrievals: [],
        debugEvents: [],
      },
    ];
    storeState.delegates = [];
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

vi.mock("@/components/chat/ChatMessage", () => ({
  ChatMessage: ({ content }: { content: string }) => <div>{content}</div>,
}));

vi.mock("@/lib/api", () => ({
  getAgents: mockGetAgents,
  getSessions: mockGetSessions,
  getSessionHistory: mockGetSessionHistory,
  getDelegateDetail: mockGetDelegateDetail,
  createSession: mockCreateSession,
  archiveSession: mockArchiveSession,
  restoreSession: mockRestoreSession,
  deleteSession: mockDeleteSession,
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => ({
    ...storeState,
    setCurrentAgent: mockSetCurrentAgent,
    setSessionsScope: mockSetSessionsScope,
    selectSession: mockSelectSession,
    continueAfterMaxSteps: mockContinueAfterMaxSteps,
    cancelAfterMaxSteps: mockCancelAfterMaxSteps,
  }),
}));

function setRoute(search: string) {
  navigationState.searchParams = new URLSearchParams(search);
  navigationState.replace.mockClear();
  navigationState.push.mockClear();
}

describe("SessionsPage", () => {
  beforeEach(() => {
    sessionFixtures = {
      default: {
        active: [
          {
            session_id: "s-1",
            title: "Alpha discussion",
            created_at: 1710000000,
            updated_at: 1710000001,
          },
          {
            session_id: "s-2",
            title: "Beta note",
            created_at: 1710000002,
            updated_at: 1710000003,
          },
        ],
        archived: [
          {
            session_id: "s-arch-default",
            title: "Stored default archive",
            created_at: 1710000004,
            updated_at: 1710000005,
            archived: true,
          },
        ],
      },
      alpha: {
        active: [
          {
            session_id: "a-1",
            title: "Alpha live",
            created_at: 1710000006,
            updated_at: 1710000007,
          },
        ],
        archived: [
          {
            session_id: "a-arch-1",
            title: "History Thread",
            created_at: 1710000008,
            updated_at: 1710000009,
            archived: true,
          },
        ],
      },
    };

    vi.clearAllMocks();
    window.localStorage.clear();
    storeState.currentAgentId = "default";
    storeState.currentSessionId = null;
    storeState.delegates = [];
    storeState.sessionsScope = "active";
    storeState.messages = [];
    storeState.isStreaming = false;
    storeState.error = null;
    storeState.maxStepsPrompt = null;
  });

  it("restores archived view state from the URL and shows the read-only detail state", async () => {
    setRoute("agent=alpha&scope=archived&q=history&session=a-arch-1");

    render(<SessionsPage />);

    await waitFor(() =>
      expect(mockGetSessions).toHaveBeenCalledWith("archived", "alpha"),
    );
    await waitFor(() =>
      expect(mockGetSessionHistory).toHaveBeenCalledWith(
        "a-arch-1",
        true,
        "alpha",
      ),
    );

    expect(screen.getByDisplayValue("history")).toBeInTheDocument();
    expect(screen.getAllByText("History Thread").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        "Archived sessions are read-only. Restore this session before continuing work.",
      ).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: "Send" }),
    ).not.toBeInTheDocument();
  });

  it("filters locally and selects an active session for live chat", async () => {
    setRoute("agent=default");
    const { rerender } = render(<SessionsPage />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Alpha discussion/i })).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "beta" },
    });
    rerender(<SessionsPage />);

    expect(screen.getByDisplayValue("beta")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Alpha discussion/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Beta note/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Beta note/i }));
    rerender(<SessionsPage />);

    await waitFor(() => expect(mockSelectSession).toHaveBeenCalledWith("s-2"));
    expect(screen.getAllByText("live:s-2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("read_files (1)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("get_weather (1)").length).toBeGreaterThan(0);
  });

  it("archives and deletes sessions through the detail actions", async () => {
    setRoute("agent=default&scope=active&session=s-1");
    const { rerender } = render(<SessionsPage />);

    await waitFor(() => expect(mockSelectSession).toHaveBeenCalledWith("s-1"));

    fireEvent.click(screen.getAllByRole("button", { name: "Archive" })[0]);
    await waitFor(() =>
      expect(mockArchiveSession).toHaveBeenCalledWith("s-1", "default"),
    );
    rerender(<SessionsPage />);
    expect(screen.getByText("Archived session.")).toBeInTheDocument();

    setRoute("agent=default&scope=active&session=s-2");
    rerender(<SessionsPage />);
    await waitFor(() => expect(mockSelectSession).toHaveBeenCalledWith("s-2"));

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await waitFor(() =>
      expect(mockDeleteSession).toHaveBeenCalledWith("s-2", false, "default"),
    );
  });

  it("restores archived sessions from the detail view without a workspace handoff", async () => {
    setRoute("agent=alpha&scope=archived&session=a-arch-1");

    render(<SessionsPage />);

    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Restore" }).length).toBeGreaterThan(0),
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Restore" })[0]);
    await waitFor(() =>
      expect(mockRestoreSession).toHaveBeenCalledWith("a-arch-1", "alpha"),
    );
  });
});
