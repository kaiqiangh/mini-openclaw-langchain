import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import RunsPage from "@/app/runs/page";
import {
  normalizeCronRun,
  normalizeUsageRun,
} from "@/lib/runs";

type UsageRecord = import("@/lib/api").UsageRecord;

const navigationState = vi.hoisted(() => ({
  pathname: "/runs",
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

let agentFixtures: Array<{
  agent_id: string;
  path: string;
  created_at: number;
  updated_at: number;
  active_sessions: number;
  archived_sessions: number;
}>;
let usageFixtures: Record<string, UsageRecord[]>;
let cronRunFixtures: Record<string, Array<Record<string, unknown>>>;
let cronFailureFixtures: Record<string, Array<Record<string, unknown>>>;
let heartbeatFixtures: Record<string, Array<Record<string, unknown>>>;

function makeUsageRecord(
  overrides: Partial<UsageRecord> & Pick<UsageRecord, "agent_id" | "timestamp_ms">,
): UsageRecord {
  return {
    schema_version: 1,
    provider: "openai",
    run_id: "run-1",
    session_id: "session-1",
    trigger_type: "chat",
    model: "gpt-5",
    model_source: "catalog",
    usage_source: "stream",
    input_tokens: 10,
    input_uncached_tokens: 10,
    input_cache_read_tokens: 0,
    input_cache_write_tokens_5m: 0,
    input_cache_write_tokens_1h: 0,
    input_cache_write_tokens_unknown: 0,
    output_tokens: 5,
    reasoning_tokens: 0,
    tool_input_tokens: 0,
    total_tokens: 15,
    priced: true,
    cost_usd: 0.125,
    pricing: {
      provider: "openai",
      model: "gpt-5",
      model_key: "gpt-5",
      priced: true,
      currency: "USD",
      source: "catalog",
      catalog_version: "test",
      long_context_applied: false,
      total_cost_usd: 0.125,
      unpriced_reason: null,
      line_items: [],
    },
    ...overrides,
  };
}

const {
  mockGetAgents,
  mockGetUsageRecords,
  mockListCronRuns,
  mockListCronFailures,
  mockListHeartbeatRuns,
} = vi.hoisted(() => ({
  mockGetAgents: vi.fn(async () => agentFixtures),
  mockGetUsageRecords: vi.fn(
    async ({ agentId = "default" }: { agentId?: string }) =>
      usageFixtures[agentId] ?? [],
  ),
  mockListCronRuns: vi.fn(async (agentId = "default") => cronRunFixtures[agentId] ?? []),
  mockListCronFailures: vi.fn(
    async (agentId = "default") => cronFailureFixtures[agentId] ?? [],
  ),
  mockListHeartbeatRuns: vi.fn(
    async (agentId = "default") => heartbeatFixtures[agentId] ?? [],
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
  getUsageRecords: mockGetUsageRecords,
  listCronRuns: mockListCronRuns,
  listCronFailures: mockListCronFailures,
  listHeartbeatRuns: mockListHeartbeatRuns,
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => ({
    currentAgentId: "default",
  }),
}));

function setRoute(search: string) {
  navigationState.searchParams = new URLSearchParams(search);
  navigationState.replace.mockClear();
  navigationState.push.mockClear();
}

function findTableRow(label: string): HTMLTableRowElement {
  const match = screen
    .getAllByText(label)
    .find((node) => node.closest("tr") instanceof HTMLTableRowElement);

  if (!match?.closest("tr")) {
    throw new Error(`No table row found for ${label}`);
  }

  return match.closest("tr") as HTMLTableRowElement;
}

describe("RunsPage", () => {
  beforeEach(() => {
    const nowMs = Date.now();
    agentFixtures = [
      {
        agent_id: "default",
        path: "/tmp/default",
        created_at: 0,
        updated_at: 0,
        active_sessions: 2,
        archived_sessions: 1,
      },
      {
        agent_id: "alpha",
        path: "/tmp/alpha",
        created_at: 0,
        updated_at: 0,
        active_sessions: 1,
        archived_sessions: 0,
      },
    ];

    usageFixtures = {
      default: [
        makeUsageRecord({
          agent_id: "default",
          timestamp_ms: nowMs - 10 * 60 * 1000,
          run_id: "run-default-chat",
          session_id: "session-default",
          total_tokens: 42,
          cost_usd: 0.420001,
        }),
      ],
      alpha: [
        makeUsageRecord({
          agent_id: "alpha",
          timestamp_ms: nowMs - 15 * 60 * 1000,
          run_id: "run-alpha-chat",
          session_id: "session-alpha",
          total_tokens: 24,
          cost_usd: 0.240001,
        }),
      ],
    };

    cronRunFixtures = {
      default: [
        {
          timestamp_ms: nowMs - 3 * 60 * 60 * 1000,
          job_id: "cron-stale",
          name: "Stale Cron",
          status: "ok",
          duration_ms: 110,
        },
        {
          timestamp_ms: nowMs - 20 * 60 * 1000,
          job_id: "cron-recent",
          name: "Recent Cron",
          status: "error",
          error: "boom",
          duration_ms: 210,
        },
      ],
      alpha: [
        {
          timestamp_ms: nowMs - 25 * 60 * 1000,
          job_id: "cron-alpha",
          name: "Alpha Cron",
          status: "ok",
          duration_ms: 180,
        },
      ],
    };

    cronFailureFixtures = {
      default: [],
      alpha: [],
    };

    heartbeatFixtures = {
      default: [
        {
          timestamp_ms: nowMs - 5 * 60 * 1000,
          status: "ok",
          duration_ms: 90,
          details: {
            session_id: "__heartbeat__",
            response_preview: "HEARTBEAT_OK",
          },
        },
      ],
      alpha: [],
    };

    vi.clearAllMocks();
  });

  it("uses the current agent and default window when query params are absent", async () => {
    setRoute("");

    render(<RunsPage />);

    await waitFor(() =>
      expect(mockGetUsageRecords).toHaveBeenCalledWith({
        sinceHours: 24,
        agentId: "default",
        limit: 500,
      }),
    );

    expect(screen.getByLabelText("Filter runs by agent")).toHaveValue("default");
    expect(screen.getByLabelText("Filter runs by time window")).toHaveValue("24h");
    expect(screen.getByLabelText("Filter runs by trigger")).toHaveValue("all");
    expect(screen.getAllByText("run-default-chat").length).toBeGreaterThan(0);
    expect(screen.queryByText("run-alpha-chat")).not.toBeInTheDocument();
  });

  it("restores filters and the selected run from a shared URL", async () => {
    const selectedRunId = normalizeUsageRun(usageFixtures.alpha[0]).rowId;
    setRoute(`agent=alpha&window=7d&trigger=chat&run=${encodeURIComponent(selectedRunId)}`);

    render(<RunsPage />);

    await waitFor(() =>
      expect(screen.getByText("Run Detail")).toBeInTheDocument(),
    );

    expect(screen.getByLabelText("Filter runs by agent")).toHaveValue("alpha");
    expect(screen.getByLabelText("Filter runs by time window")).toHaveValue("7d");
    expect(screen.getByLabelText("Filter runs by trigger")).toHaveValue("chat");
    expect(screen.getAllByText("run-alpha-chat").length).toBeGreaterThan(0);

    const drawer = screen.getByText("Run Detail").closest("aside");
    expect(drawer).not.toBeNull();
    expect(
      within(drawer as HTMLElement).getByText("Chat Usage"),
    ).toBeInTheDocument();
    expect(
      within(drawer as HTMLElement).getByText(
        "This row comes from persisted chat token and cost accounting. It is recorded activity, not a scheduler status stream.",
      ),
    ).toBeInTheDocument();
    expect(
      within(drawer as HTMLElement).getByRole("link", { name: "Open Session" }),
    ).toHaveAttribute(
      "href",
      "/sessions?agent=alpha&session=session-alpha",
    );
  });

  it("applies the selected window across scheduler rows and keeps drawer state in the URL", async () => {
    const recentCronRowId = normalizeCronRun(cronRunFixtures.default[1]).rowId;
    setRoute("agent=default&window=1h&trigger=cron");
    const { rerender } = render(<RunsPage />);

    await waitFor(() =>
      expect(screen.getAllByText("cron-recent").length).toBeGreaterThan(0),
    );

    expect(screen.queryByText("cron-stale")).not.toBeInTheDocument();

    fireEvent.click(findTableRow("cron-recent"));
    expect(navigationState.push).toHaveBeenCalled();
    expect(navigationState.searchParams.get("run")).toBe(recentCronRowId);

    rerender(<RunsPage />);

    const drawer = await screen.findByText("Run Detail");
    const aside = drawer.closest("aside") as HTMLElement;
    const runIdPanel = within(aside).getByText("Run ID").parentElement;
    const sessionIdPanel = within(aside).getByText("Session ID").parentElement;

    expect(runIdPanel).not.toBeNull();
    expect(sessionIdPanel).not.toBeNull();
    expect(runIdPanel).toHaveTextContent("—");
    expect(sessionIdPanel).toHaveTextContent("—");

    fireEvent.click(within(aside).getByRole("button", { name: "Close" }));
    expect(navigationState.searchParams.get("run")).toBeNull();

    rerender(<RunsPage />);
    expect(screen.queryByText("Run Detail")).not.toBeInTheDocument();
  });
});
