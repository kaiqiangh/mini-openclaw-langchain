import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AppProvider, useAppStore } from "@/lib/store";

const {
  mockGetAgents,
  mockCreateAgentWorkspace,
  mockDeleteAgentWorkspace,
  mockGetRagMode,
  mockGetSessions,
  mockCreateSession,
  mockArchiveSession,
  mockRestoreSession,
  mockDeleteSession,
  mockGetSessionHistory,
  mockReadWorkspaceFile,
  mockSaveWorkspaceFile,
  mockSetRagMode,
  mockStreamChat,
} = vi.hoisted(() => ({
  mockGetAgents: vi.fn(async () => [
    {
      agent_id: "default",
      path: "/tmp/default",
      created_at: 0,
      updated_at: 0,
      active_sessions: 0,
      archived_sessions: 0,
    },
    {
      agent_id: "elon",
      path: "/tmp/elon",
      created_at: 0,
      updated_at: 0,
      active_sessions: 1,
      archived_sessions: 0,
    },
  ]),
  mockCreateAgentWorkspace: vi.fn(async () => ({
    agent_id: "extra",
    path: "/tmp/extra",
    created_at: 0,
    updated_at: 0,
    active_sessions: 0,
    archived_sessions: 0,
  })),
  mockDeleteAgentWorkspace: vi.fn(async () => undefined),
  mockGetRagMode: vi.fn(async () => false),
  mockGetSessions: vi.fn(async (_scope?: string, agentId?: string) =>
    agentId === "elon"
      ? [
          {
            session_id: "e1",
            title: "Elon Session",
            created_at: 0,
            updated_at: 0,
          },
        ]
      : [],
  ),
  mockCreateSession: vi.fn(async () => ({
    session_id: "s1",
    title: "New Session",
  })),
  mockArchiveSession: vi.fn(async () => undefined),
  mockRestoreSession: vi.fn(async () => undefined),
  mockDeleteSession: vi.fn(async () => undefined),
  mockGetSessionHistory: vi.fn(async () => ({
    session_id: "s1",
    messages: [],
  })),
  mockReadWorkspaceFile: vi.fn(
    async (path: string, agentId?: string) =>
      `content:${agentId ?? "default"}:${path}`,
  ),
  mockSaveWorkspaceFile: vi.fn(async () => undefined),
  mockSetRagMode: vi.fn(async (enabled: boolean) => enabled),
  mockStreamChat: vi.fn(async () => undefined),
}));

vi.mock("@/lib/api", () => ({
  getAgents: mockGetAgents,
  createAgentWorkspace: mockCreateAgentWorkspace,
  deleteAgentWorkspace: mockDeleteAgentWorkspace,
  getRagMode: mockGetRagMode,
  getSessions: mockGetSessions,
  createSession: mockCreateSession,
  archiveSession: mockArchiveSession,
  restoreSession: mockRestoreSession,
  deleteSession: mockDeleteSession,
  getSessionHistory: mockGetSessionHistory,
  readWorkspaceFile: mockReadWorkspaceFile,
  saveWorkspaceFile: mockSaveWorkspaceFile,
  setRagMode: mockSetRagMode,
  streamChat: mockStreamChat,
}));

function Probe() {
  const store = useAppStore();

  if (!store.initialized) {
    return <div>booting</div>;
  }

  return (
    <div>
      <div data-testid="file">{store.selectedFilePath}</div>
      <button onClick={() => store.setSelectedFilePath("workspace/AGENTS.md")}>
        switch-file
      </button>
      <button onClick={() => store.updateSelectedFileContent("edited")}>
        edit
      </button>
      <button onClick={() => store.saveSelectedFile()}>save</button>
    </div>
  );
}

function AgentProbe() {
  const store = useAppStore();
  if (!store.initialized) return <div>booting</div>;

  return (
    <div>
      <div data-testid="agent">{store.currentAgentId}</div>
      <div data-testid="session-count">{store.sessions.length}</div>
      <div data-testid="file-content">{store.selectedFileContent}</div>
      <button onClick={() => store.setCurrentAgent("elon")}>
        switch-agent
      </button>
    </div>
  );
}

describe("store editor save flow", () => {
  it("loads file, edits content, and saves through API", async () => {
    render(
      <AppProvider>
        <Probe />
      </AppProvider>,
    );

    await waitFor(() =>
      expect(screen.queryByText("booting")).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("switch-file"));
    await waitFor(() =>
      expect(screen.getByTestId("file")).toHaveTextContent(
        "workspace/AGENTS.md",
      ),
    );

    fireEvent.click(screen.getByText("edit"));
    fireEvent.click(screen.getByText("save"));

    await waitFor(() => expect(mockSaveWorkspaceFile).toHaveBeenCalled());
    expect(mockSaveWorkspaceFile).toHaveBeenLastCalledWith(
      "workspace/AGENTS.md",
      "edited",
      "default",
    );
  });

  it("switches session and file context by selected agent", async () => {
    render(
      <AppProvider>
        <AgentProbe />
      </AppProvider>,
    );

    await waitFor(() =>
      expect(screen.queryByText("booting")).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("switch-agent"));

    await waitFor(() =>
      expect(screen.getByTestId("agent")).toHaveTextContent("elon"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("session-count")).toHaveTextContent("1"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("file-content")).toHaveTextContent(
        "content:elon:memory/MEMORY.md",
      ),
    );
  });
});
