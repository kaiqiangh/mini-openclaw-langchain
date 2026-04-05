import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

import DelegatesPage from "@/app/delegates/page";

const navigationState = vi.hoisted(() => ({
  pathname: "/delegates",
  searchParams: new URLSearchParams("agent=crypto-rd&session=s-9"),
}));

const storeState = vi.hoisted(() => ({
  currentAgentId: "default",
  currentSessionId: "s-1" as string | null,
  delegates: [] as Array<{
    delegate_id: string;
    role: string;
    task: string;
    status: "running" | "completed" | "failed" | "timeout";
    sub_session_id: string;
    created_at: number;
  }>,
}));

const { mockListDelegates, mockGetDelegateDetail } = vi.hoisted(() => ({
  mockListDelegates: vi.fn(),
  mockGetDelegateDetail: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useSearchParams: () => navigationState.searchParams,
}));

vi.mock("@/lib/api", () => ({
  listDelegates: mockListDelegates,
  getDelegateDetail: mockGetDelegateDetail,
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => ({
    ...storeState,
  }),
}));

describe("DelegatesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    storeState.currentAgentId = "default";
    storeState.currentSessionId = "s-1";
    storeState.delegates = [];
    navigationState.searchParams = new URLSearchParams("agent=crypto-rd&session=s-9");

    mockListDelegates.mockResolvedValue({
      delegates: [
        {
          delegate_id: "del-1",
          role: "researcher",
          task: "Investigate issue",
          status: "completed",
          sub_session_id: "sub-1",
          created_at: 1710000000000,
        },
      ],
    });
    mockGetDelegateDetail.mockResolvedValue({
      delegate_id: "del-1",
      agent_id: "crypto-rd",
      parent_session_id: "s-9",
      role: "researcher",
      task: "Investigate issue",
      status: "completed",
      sub_session_id: "sub-1",
      created_at: 1710000000000,
      allowed_tools: ["web_search"],
      result_summary: "Found the issue.",
    });
  });

  it("uses the URL-selected agent and session when present", async () => {
    render(<DelegatesPage />);

    await waitFor(() =>
      expect(mockListDelegates).toHaveBeenCalledWith("crypto-rd", "s-9"),
    );
    await waitFor(() =>
      expect(screen.getByText("Investigate issue")).toBeInTheDocument(),
    );
    expect(screen.getByText("Agent crypto-rd")).toBeInTheDocument();
    expect(screen.getByText("Session s-9")).toBeInTheDocument();
  });

  it("falls back to the active store session when the URL does not provide one", async () => {
    navigationState.searchParams = new URLSearchParams();
    storeState.currentAgentId = "default";
    storeState.currentSessionId = "s-1";
    storeState.delegates = [
      {
        delegate_id: "del-live",
        role: "analyst",
        task: "Check latest trades",
        status: "running",
        sub_session_id: "sub-live",
        created_at: 1710000000100,
      },
    ];
    mockGetDelegateDetail.mockResolvedValue({
      delegate_id: "del-live",
      agent_id: "default",
      parent_session_id: "s-1",
      role: "analyst",
      task: "Check latest trades",
      status: "running",
      sub_session_id: "sub-live",
      created_at: 1710000000100,
      allowed_tools: ["read_files"],
    });

    render(<DelegatesPage />);

    await waitFor(() =>
      expect(mockListDelegates).toHaveBeenCalledWith("default", "s-1"),
    );
    await waitFor(() =>
      expect(screen.getAllByText("Check latest trades")).toHaveLength(2),
    );
  });

  it("shows an empty state when no session can be resolved", async () => {
    navigationState.searchParams = new URLSearchParams();
    storeState.currentSessionId = null;

    render(<DelegatesPage />);

    expect(
      screen.getByText(/select a session or open this page with agent and session query parameters/i),
    ).toBeInTheDocument();
    expect(mockListDelegates).not.toHaveBeenCalled();
  });
});
