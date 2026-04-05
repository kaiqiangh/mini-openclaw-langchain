import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

import SetupPage from "@/app/setup/page";

const {
  mockGetSetupStatus,
  mockConfigureSystem,
  mockGetAgents,
  mockListHooks,
  mockGetHookAudit,
  mockCreateHook,
  mockDeleteHook,
  mockTestHook,
} = vi.hoisted(() => ({
  mockGetSetupStatus: vi.fn(),
  mockConfigureSystem: vi.fn(),
  mockGetAgents: vi.fn(),
  mockListHooks: vi.fn(),
  mockGetHookAudit: vi.fn(),
  mockCreateHook: vi.fn(),
  mockDeleteHook: vi.fn(),
  mockTestHook: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getSetupStatus: mockGetSetupStatus,
  configureSystem: mockConfigureSystem,
  getAgents: mockGetAgents,
  listHooks: mockListHooks,
  getHookAudit: mockGetHookAudit,
  createHook: mockCreateHook,
  deleteHook: mockDeleteHook,
  testHook: mockTestHook,
}));

describe("SetupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfigureSystem.mockResolvedValue({
      configured: true,
      admin_token_configured: true,
      llm_provider: "openai",
      message: "saved",
    });
    mockCreateHook.mockResolvedValue({
      id: "audit-pre-tool",
      type: "pre_tool_use",
      handler: "hooks/audit.py",
      mode: "sync",
      timeout_ms: 10000,
    });
    mockDeleteHook.mockResolvedValue({ deleted: "audit-pre-tool" });
    mockTestHook.mockResolvedValue({
      hook_id: "audit-pre-tool",
      allow: true,
      reason: "",
    });
  });

  it("renders the hooks operator panel when setup is already complete", async () => {
    mockGetSetupStatus.mockResolvedValue({
      needs_setup: false,
      admin_token_configured: true,
      llm_configured: true,
      default_agent_exists: true,
    });
    mockGetAgents.mockResolvedValue([
      {
        agent_id: "crypto-rd",
        path: "/tmp/crypto-rd",
        created_at: 0,
        updated_at: 0,
        active_sessions: 1,
        archived_sessions: 0,
      },
    ]);
    mockListHooks.mockResolvedValue([
      {
        id: "audit-pre-tool",
        type: "pre_tool_use",
        handler: "hooks/audit.py",
        mode: "sync",
        timeout_ms: 10000,
      },
    ]);
    mockGetHookAudit.mockResolvedValue([
      {
        event: "hook_pre_tool_use",
        timestamp_ms: 1710000000000,
        details: { tool_name: "read_files" },
      },
    ]);

    render(<SetupPage />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Hooks Panel" })).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(mockListHooks).toHaveBeenCalledWith("crypto-rd"),
    );
    await waitFor(() =>
      expect(screen.getByText("audit-pre-tool")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Setup Wizard" })).not.toBeInTheDocument();
  });

  it("keeps the setup wizard when the system still needs setup", async () => {
    mockGetSetupStatus.mockResolvedValue({
      needs_setup: true,
      admin_token_configured: false,
      llm_configured: false,
      default_agent_exists: true,
    });
    mockGetAgents.mockResolvedValue([]);
    mockListHooks.mockResolvedValue([]);
    mockGetHookAudit.mockResolvedValue([]);

    render(<SetupPage />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Setup Wizard" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Hooks Panel" })).not.toBeInTheDocument();
  });
});
