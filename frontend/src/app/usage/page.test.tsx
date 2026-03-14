import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import UsagePage from "@/app/usage/page";
import type { UsageRecord, UsageSummary } from "@/lib/api";

const storeState = vi.hoisted(() => ({
  currentAgentId: "default",
  setCurrentAgent: vi.fn(),
}));

const fixtures = vi.hoisted(() => ({
  agents: [
    {
      agent_id: "default",
      path: "/tmp/default",
      created_at: 0,
      updated_at: 0,
      active_sessions: 1,
      archived_sessions: 0,
    },
  ],
  summary: {
    totals: {
      runs: 4,
      priced_runs: 4,
      unpriced_runs: 0,
      input_tokens: 100,
      input_uncached_tokens: 80,
      input_cache_read_tokens: 20,
      input_cache_write_tokens_5m: 5,
      input_cache_write_tokens_1h: 5,
      input_cache_write_tokens_unknown: 0,
      output_tokens: 60,
      reasoning_tokens: 10,
      tool_input_tokens: 4,
      total_tokens: 160,
      cost_usd: 0.42,
    },
    by_provider_model: [
      {
        provider: "openai",
        model: "gpt-5",
        runs: 4,
        priced_runs: 4,
        unpriced_runs: 0,
        input_tokens: 100,
        input_uncached_tokens: 80,
        input_cache_read_tokens: 20,
        input_cache_write_tokens_5m: 5,
        input_cache_write_tokens_1h: 5,
        input_cache_write_tokens_unknown: 0,
        output_tokens: 60,
        reasoning_tokens: 10,
        tool_input_tokens: 4,
        total_tokens: 160,
        cost_usd: 0.42,
      },
    ],
    by_provider: [
      {
        provider: "openai",
        runs: 4,
        priced_runs: 4,
        unpriced_runs: 0,
        input_tokens: 100,
        output_tokens: 60,
        total_tokens: 160,
        cost_usd: 0.42,
      },
    ],
    count: 4,
  } as UsageSummary,
  records: [] as UsageRecord[],
}));

const apiMocks = vi.hoisted(() => ({
  getAgents: vi.fn(async () => fixtures.agents),
  getUsageSummary: vi.fn(async () => fixtures.summary),
  getUsageRecords: vi.fn(async () => fixtures.records),
}));

vi.mock("@/lib/api", () => apiMocks);

vi.mock("@/lib/store", () => ({
  useAppStore: () => storeState,
}));

function setViewportMode(desktop: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query === "(min-width: 1024px)" ? desktop : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function makeRecord(overrides: Partial<UsageRecord> = {}): UsageRecord {
  return {
    schema_version: 1,
    timestamp_ms: 1_710_000_000_000,
    agent_id: "default",
    provider: "openai",
    run_id: "run-1",
    session_id: "session-1",
    trigger_type: "chat",
    model: "gpt-5",
    model_source: "catalog",
    usage_source: "stream",
    input_tokens: 100,
    input_uncached_tokens: 80,
    input_cache_read_tokens: 20,
    input_cache_write_tokens_5m: 5,
    input_cache_write_tokens_1h: 5,
    input_cache_write_tokens_unknown: 0,
    output_tokens: 60,
    reasoning_tokens: 10,
    tool_input_tokens: 4,
    total_tokens: 160,
    priced: true,
    cost_usd: 0.42,
    pricing: {
      provider: "openai",
      model: "gpt-5",
      model_key: "gpt-5",
      priced: true,
      currency: "USD",
      source: "catalog",
      catalog_version: "test",
      long_context_applied: false,
      total_cost_usd: 0.42,
      unpriced_reason: null,
      line_items: [],
    },
    ...overrides,
  };
}

describe("UsagePage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setViewportMode(false);
    fixtures.records = [makeRecord()];
    storeState.currentAgentId = "default";
    storeState.setCurrentAgent.mockReset();
    apiMocks.getAgents.mockClear();
    apiMocks.getUsageSummary.mockClear();
    apiMocks.getUsageRecords.mockClear();
  });

  it("uses overview-first defaults on mobile first visit", async () => {
    render(<UsagePage />);

    await waitFor(() => expect(apiMocks.getUsageRecords).toHaveBeenCalled());

    expect(screen.getByText("Priced Cost (USD)")).toBeInTheDocument();
    expect(screen.getByText("Token Trend")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-provider-model-scroll")).not.toBeInTheDocument();
    expect(screen.queryByTestId("usage-recent-runs-scroll")).not.toBeInTheDocument();
  });

  it("uses a scrolling stack that does not shrink top-level panels", async () => {
    const { container } = render(<UsagePage />);

    await waitFor(() => expect(apiMocks.getUsageRecords).toHaveBeenCalled());

    const stack = container.querySelector("#main-content > section");
    expect(stack).not.toBeNull();
    expect(stack?.className).toContain("ui-page-stack");
    expect(stack?.className).not.toContain("flex-col");
  });

  it("keeps all sections expanded on desktop first visit", async () => {
    setViewportMode(true);
    render(<UsagePage />);

    await waitFor(() => expect(apiMocks.getUsageRecords).toHaveBeenCalled());

    expect(screen.getByTestId("usage-provider-model-scroll")).toBeInTheDocument();
    expect(screen.getByTestId("usage-recent-runs-scroll")).toBeInTheDocument();
  });

  it("restores saved section state over responsive defaults", async () => {
    window.localStorage.setItem(
      "mini-openclaw:usage-sections:v1",
      JSON.stringify({
        filters: false,
        summary: false,
        trend: true,
        provider_model: true,
        recent_runs: false,
      }),
    );

    render(<UsagePage />);

    await waitFor(() => expect(apiMocks.getUsageRecords).toHaveBeenCalled());

    expect(
      screen.queryByRole("combobox", { name: "Agent" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Priced Cost (USD)")).not.toBeInTheDocument();
    expect(screen.getByTestId("usage-provider-model-scroll")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-recent-runs-scroll")).not.toBeInTheDocument();
  });

  it("supports page-level expand and collapse controls", async () => {
    render(<UsagePage />);

    await waitFor(() => expect(apiMocks.getUsageRecords).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Expand All Sections" }));
    expect(screen.getByTestId("usage-provider-model-scroll")).toBeInTheDocument();
    expect(screen.getByTestId("usage-recent-runs-scroll")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Collapse All Sections" }));
    expect(screen.queryByText("Priced Cost (USD)")).not.toBeInTheDocument();
    expect(screen.queryByTestId("usage-provider-model-scroll")).not.toBeInTheDocument();
  });

  it("supports per-section toggle controls and capped data panels", async () => {
    setViewportMode(true);
    render(<UsagePage />);

    await waitFor(() => expect(apiMocks.getUsageRecords).toHaveBeenCalled());

    const providerPanel = screen.getByText("By Provider / Model").closest(".panel-shell");
    expect(providerPanel).not.toBeNull();

    fireEvent.click(
      within(providerPanel as HTMLElement).getByRole("button", { name: "Collapse" }),
    );
    expect(screen.queryByTestId("usage-provider-model-scroll")).not.toBeInTheDocument();

    fireEvent.click(
      within(providerPanel as HTMLElement).getByRole("button", { name: "Expand" }),
    );
    expect(screen.getByTestId("usage-provider-model-scroll")).toBeInTheDocument();

    const providerScroll = screen.getByTestId("usage-provider-model-scroll");
    expect(providerScroll.className).toContain("max-h-[26rem]");
    expect(providerScroll.className).toContain("lg:max-h-[40vh]");
    expect(providerScroll.className).toContain("overflow-y-auto");

    const runScroll = screen.getByTestId("usage-recent-runs-scroll");
    expect(runScroll.className).toContain("max-h-[26rem]");
    expect(runScroll.className).toContain("lg:max-h-[40vh]");
    expect(runScroll.className).toContain("overflow-y-auto");
  });
});
