import React from "react";
import {
  act,
  renderHook,
} from "@testing-library/react";

import { AppProvider, useAppStore } from "@/lib/store";

const apiMocks = vi.hoisted(() => ({
  archiveSession: vi.fn(),
  bulkDeleteAgentWorkspaces: vi.fn(),
  bulkExportAgentWorkspaces: vi.fn(),
  bulkPatchAgentRuntime: vi.fn(),
  createAgentWorkspace: vi.fn(),
  createSession: vi.fn(),
  deleteAgentWorkspace: vi.fn(),
  deleteSession: vi.fn(),
  generateSessionTitle: vi.fn(),
  getAgents: vi.fn(),
  getDelegateDetail: vi.fn(),
  getRagMode: vi.fn(),
  getSessionHistory: vi.fn(),
  getSessions: vi.fn(),
  listDelegates: vi.fn(),
  readWorkspaceFile: vi.fn(),
  restoreSession: vi.fn(),
  saveWorkspaceFile: vi.fn(),
  setRagMode: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("@/lib/api", () => apiMocks);

const defaultAgent = {
  agent_id: "default",
  path: "/tmp/default",
  created_at: 1,
  updated_at: 1,
  active_sessions: 1,
  archived_sessions: 0,
};

const defaultSession = {
  session_id: "sess_1",
  title: "Session 1",
  created_at: 1,
  updated_at: 1,
  archived: false,
};

function wrapper({ children }: { children: React.ReactNode }) {
  return <AppProvider>{children}</AppProvider>;
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

async function flushMicrotasks(rounds = 8) {
  for (let i = 0; i < rounds; i += 1) {
    await Promise.resolve();
  }
}

describe("delegate store wiring", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();

    apiMocks.getAgents.mockResolvedValue([defaultAgent]);
    apiMocks.getRagMode.mockResolvedValue(false);
    apiMocks.getSessions.mockResolvedValue([defaultSession]);
    apiMocks.getSessionHistory.mockResolvedValue({
      session_id: "sess_1",
      messages: [],
    });
    apiMocks.readWorkspaceFile.mockResolvedValue("# MEMORY");
    apiMocks.createSession.mockResolvedValue({ session_id: "sess_1" });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("hydrates terminal delegate detail once and does not refetch it on later polls", async () => {
    apiMocks.listDelegates.mockResolvedValue({
      delegates: [
        {
          delegate_id: "del_done",
          role: "researcher",
          task: "Summarize memory",
          status: "completed",
          sub_session_id: "sub_done",
          created_at: 1,
        },
      ],
    });
    apiMocks.getDelegateDetail.mockResolvedValue({
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
    });

    const { result } = renderHook(() => useAppStore(), { wrapper });

    await act(async () => {
      await flushMicrotasks();
    });

    expect(result.current.delegates[0]?.detail?.result_summary).toBe(
      "Delegate finished successfully.",
    );
    expect(apiMocks.getDelegateDetail).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await flushMicrotasks(2);
    });

    expect(apiMocks.getDelegateDetail).toHaveBeenCalledTimes(1);
  });

  it("does not leak old-session delegate data during a session switch", async () => {
    const oldDelegateList = deferred<{
      delegates: Array<{
        delegate_id: string;
        role: string;
        task: string;
        status: "running";
        sub_session_id: string;
        created_at: number;
      }>;
    }>();
    apiMocks.getSessions.mockResolvedValue([
      defaultSession,
      {
        session_id: "sess_2",
        title: "Session 2",
        created_at: 2,
        updated_at: 2,
        archived: false,
      },
    ]);
    apiMocks.getSessionHistory.mockImplementation(async (sessionId: string) => ({
      session_id: sessionId,
      messages: [],
    }));
    apiMocks.listDelegates.mockImplementation(async (_agentId: string, sessionId: string) => {
      if (sessionId === "sess_1") {
        return oldDelegateList.promise;
      }
      return { delegates: [] };
    });

    const { result } = renderHook(() => useAppStore(), { wrapper });

    await act(async () => {
      await flushMicrotasks();
    });

    await act(async () => {
      await result.current.selectSession("sess_2");
      await flushMicrotasks();
    });

    await act(async () => {
      oldDelegateList.resolve({
        delegates: [
          {
            delegate_id: "del_old",
            role: "researcher",
            task: "Old session delegate",
            status: "running",
            sub_session_id: "sub_old",
            created_at: 1,
          },
        ],
      });
      await flushMicrotasks();
    });

    expect(result.current.currentSessionId).toBe("sess_2");
    expect(
      result.current.delegates.some(
        (delegate) => delegate.delegate_id === "del_old",
      ),
    ).toBe(false);
  });

  it("restores the previous session when the next session history load fails", async () => {
    apiMocks.getSessions.mockResolvedValue([
      defaultSession,
      {
        session_id: "sess_2",
        title: "Session 2",
        created_at: 2,
        updated_at: 2,
        archived: false,
      },
    ]);
    apiMocks.getSessionHistory.mockImplementation(async (sessionId: string) => {
      if (sessionId === "sess_2") {
        throw new Error("history failed");
      }
      return {
        session_id: sessionId,
        messages: [
          {
            role: "user",
            content: "original session message",
            timestamp_ms: 1,
          },
        ],
      };
    });
    apiMocks.listDelegates.mockResolvedValue({ delegates: [] });

    const { result } = renderHook(() => useAppStore(), { wrapper });

    await act(async () => {
      await flushMicrotasks();
    });

    expect(result.current.currentSessionId).toBe("sess_1");
    expect(result.current.messages[0]?.content).toBe("original session message");

    let thrown: Error | null = null;
    await act(async () => {
      try {
        await result.current.selectSession("sess_2");
      } catch (error) {
        thrown = error as Error;
      }
      await flushMicrotasks();
    });

    expect(thrown?.message).toBe("history failed");
    expect(result.current.currentSessionId).toBe("sess_1");
    expect(result.current.messages[0]?.content).toBe("original session message");
  });

  it("prevents overlapping terminal detail fetches while a poll is already in flight", async () => {
    const detailRequest = deferred<{
      delegate_id: string;
      role: string;
      task: string;
      status: "completed";
      sub_session_id: string;
      created_at: number;
      agent_id: string;
      parent_session_id: string;
      allowed_tools: string[];
      result_summary: string;
    }>();
    apiMocks.listDelegates.mockResolvedValue({
      delegates: [
        {
          delegate_id: "del_done",
          role: "researcher",
          task: "Summarize memory",
          status: "completed",
          sub_session_id: "sub_done",
          created_at: 1,
        },
      ],
    });
    apiMocks.getDelegateDetail.mockImplementation(
      async () => detailRequest.promise,
    );

    renderHook(() => useAppStore(), { wrapper });

    await act(async () => {
      await flushMicrotasks();
    });
    expect(apiMocks.getDelegateDetail).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(4000);
      await flushMicrotasks(2);
    });

    expect(apiMocks.getDelegateDetail).toHaveBeenCalledTimes(1);

    await act(async () => {
      detailRequest.resolve({
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
      });
      await flushMicrotasks();
    });
  });

  it("stops retrying a terminal detail fetch after the retry budget is exhausted", async () => {
    apiMocks.listDelegates.mockResolvedValue({
      delegates: [
        {
          delegate_id: "del_done",
          role: "researcher",
          task: "Summarize memory",
          status: "completed",
          sub_session_id: "sub_done",
          created_at: 1,
        },
      ],
    });
    apiMocks.getDelegateDetail.mockRejectedValue(new Error("detail failed"));

    const { result } = renderHook(() => useAppStore(), { wrapper });

    await act(async () => {
      await flushMicrotasks();
    });

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await flushMicrotasks(2);
    });

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await flushMicrotasks(2);
    });
    expect(apiMocks.getDelegateDetail).toHaveBeenCalledTimes(3);
    expect(result.current.delegates[0]?.detail?.result_summary).toBe(
      "Delegate completed, but the detailed result could not be loaded.",
    );

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await flushMicrotasks(2);
    });

    expect(apiMocks.getDelegateDetail).toHaveBeenCalledTimes(3);
  });
});
