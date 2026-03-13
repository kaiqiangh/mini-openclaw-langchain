import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import SchedulerPage from "@/app/scheduler/page";
import type {
  CronJob,
  HeartbeatConfig,
  SchedulerMetrics,
  SchedulerMetricsSeries,
} from "@/lib/api";

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
  jobs: [] as CronJob[],
  runs: [] as Array<Record<string, unknown>>,
  failures: [] as Array<Record<string, unknown>>,
  heartbeatRuns: [] as Array<Record<string, unknown>>,
  heartbeat: {
    enabled: true,
    interval_seconds: 300,
    timezone: "UTC",
    active_start_hour: 9,
    active_end_hour: 21,
    session_id: "__heartbeat__",
  } as HeartbeatConfig,
  metrics: {
    agent_id: "default",
    window: "24h",
    since_ms: 0,
    generated_at_ms: 0,
    totals: {
      events: 12,
      cron_events: 9,
      heartbeat_events: 3,
    },
    cron: {
      runs: 9,
      ok: 8,
      error: 1,
      success_rate: 88.9,
    },
    heartbeat: {
      runs: 3,
      ok: 3,
      error: 0,
      skipped: 0,
    },
    duration: {
      count: 12,
      avg_ms: 120,
      min_ms: 50,
      max_ms: 300,
      p50_ms: 100,
      p90_ms: 220,
      p99_ms: 290,
    },
    latency: {
      count: 12,
      avg_ms: 160,
      min_ms: 60,
      max_ms: 360,
      p50_ms: 140,
      p90_ms: 260,
      p99_ms: 330,
    },
    status_breakdown: {
      ok: 11,
      error: 1,
    },
  } as SchedulerMetrics,
  series: {
    agent_id: "default",
    window: "24h",
    bucket: "15m",
    since_ms: 0,
    generated_at_ms: 0,
    points: [],
  } as SchedulerMetricsSeries,
}));

const apiMocks = vi.hoisted(() => ({
  getAgents: vi.fn(async () => fixtures.agents),
  listCronJobs: vi.fn(async () => fixtures.jobs),
  listCronRuns: vi.fn(async () => fixtures.runs),
  listCronFailures: vi.fn(async () => fixtures.failures),
  getHeartbeatConfig: vi.fn(async () => fixtures.heartbeat),
  listHeartbeatRuns: vi.fn(async () => fixtures.heartbeatRuns),
  getSchedulerMetrics: vi.fn(async () => fixtures.metrics),
  getSchedulerMetricsTimeseries: vi.fn(async () => fixtures.series),
  createCronJob: vi.fn(async () => undefined),
  updateCronJob: vi.fn(async () => undefined),
  deleteCronJob: vi.fn(async () => undefined),
  runCronJob: vi.fn(async () => undefined),
  updateHeartbeatConfig: vi.fn(async () => undefined),
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

function renderPage() {
  return render(<SchedulerPage />);
}

describe("SchedulerPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setViewportMode(false);
    fixtures.jobs = [];
    fixtures.runs = [];
    fixtures.failures = [];
    fixtures.heartbeatRuns = [];
    fixtures.series = {
      ...fixtures.series,
      points: [],
    };
    storeState.currentAgentId = "default";
    storeState.setCurrentAgent.mockReset();
    Object.assign(apiMocks, {
      getAgents: apiMocks.getAgents.mockClear(),
      listCronJobs: apiMocks.listCronJobs.mockClear(),
      listCronRuns: apiMocks.listCronRuns.mockClear(),
      listCronFailures: apiMocks.listCronFailures.mockClear(),
      getHeartbeatConfig: apiMocks.getHeartbeatConfig.mockClear(),
      listHeartbeatRuns: apiMocks.listHeartbeatRuns.mockClear(),
      getSchedulerMetrics: apiMocks.getSchedulerMetrics.mockClear(),
      getSchedulerMetricsTimeseries:
        apiMocks.getSchedulerMetricsTimeseries.mockClear(),
      createCronJob: apiMocks.createCronJob.mockClear(),
      updateCronJob: apiMocks.updateCronJob.mockClear(),
      deleteCronJob: apiMocks.deleteCronJob.mockClear(),
      runCronJob: apiMocks.runCronJob.mockClear(),
      updateHeartbeatConfig: apiMocks.updateHeartbeatConfig.mockClear(),
    });
  });

  it("uses overview-first defaults on mobile first visit", async () => {
    renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    expect(screen.getByText("Scheduler Events")).toBeInTheDocument();
    expect(screen.getByText("No Trend Data")).toBeInTheDocument();
    expect(screen.queryByText("Create Cron Job")).not.toBeInTheDocument();
    expect(screen.queryByText("No Cron Jobs")).not.toBeInTheDocument();
    expect(screen.queryByText("Save Heartbeat")).not.toBeInTheDocument();
  });

  it("uses a scrolling stack that does not shrink top-level panels", async () => {
    const { container } = renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    const stack = container.querySelector("#main-content > section");
    expect(stack).not.toBeNull();
    expect(stack?.className).toContain("space-y-3");
    expect(stack?.className).not.toContain("flex-col");
  });

  it("keeps all sections expanded on desktop first visit", async () => {
    setViewportMode(true);
    renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    expect(screen.getByText("No Cron Jobs")).toBeInTheDocument();
    expect(screen.getByText("Save Heartbeat")).toBeInTheDocument();
    expect(screen.getByText("No Runs")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New Job" }).length).toBeGreaterThan(
      0,
    );
  });

  it("restores saved section state over responsive defaults", async () => {
    window.localStorage.setItem(
      "mini-openclaw:scheduler-sections:v1",
      JSON.stringify({
        metrics: false,
        trend: false,
        cron: true,
        heartbeat: false,
        recent_runs: false,
        recent_failures: false,
        heartbeat_runs: false,
      }),
    );

    renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    expect(screen.getByText("No Cron Jobs")).toBeInTheDocument();
    expect(screen.queryByText("Scheduler Events")).not.toBeInTheDocument();
    expect(screen.queryByText("No Trend Data")).not.toBeInTheDocument();
  });

  it("supports page-level expand and collapse controls", async () => {
    renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Expand All Sections" }));
    expect(screen.getByText("No Cron Jobs")).toBeInTheDocument();
    expect(screen.getByText("Save Heartbeat")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Collapse All Sections" }));
    expect(screen.queryByText("Scheduler Events")).not.toBeInTheDocument();
    expect(screen.queryByText("No Cron Jobs")).not.toBeInTheDocument();
  });

  it("applies capped scroll containers to data-heavy sections", async () => {
    setViewportMode(true);
    fixtures.jobs = [
      {
        id: "job-1",
        name: "Nightly sync",
        schedule_type: "cron",
        schedule: "0 * * * *",
        prompt: "sync",
        enabled: true,
        next_run_ts: 1,
        created_at: 0,
        updated_at: 0,
        last_run_ts: 0,
        last_success_ts: 0,
        failure_count: 0,
        last_error: "",
      },
    ];
    fixtures.runs = [{ timestamp_ms: 1, name: "Nightly sync", status: "ok" }];
    fixtures.failures = [
      { timestamp_ms: 1, name: "Nightly sync", error: "timeout" },
    ];
    fixtures.heartbeatRuns = [
      {
        timestamp_ms: 1,
        status: "ok",
        details: { response_preview: "HEARTBEAT_OK" },
      },
    ];

    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("scheduler-cron-scroll")).toBeInTheDocument(),
    );

    for (const testId of [
      "scheduler-cron-scroll",
      "scheduler-recent-runs-scroll",
      "scheduler-recent-failures-scroll",
      "scheduler-heartbeat-runs-scroll",
    ]) {
      const panel = screen.getByTestId(testId);
      expect(panel.className).toContain("max-h-[26rem]");
      expect(panel.className).toContain("lg:max-h-[40vh]");
      expect(panel.className).toContain("overflow-y-auto");
    }
  });

  it("supports per-section toggle controls", async () => {
    renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Expand All Sections" }));

    const cronPanel = screen.getByText("Cron Jobs").closest(".panel-shell");
    expect(cronPanel).not.toBeNull();
    fireEvent.click(
      within(cronPanel as HTMLElement).getByRole("button", { name: "Collapse" }),
    );

    expect(screen.queryByText("No Cron Jobs")).not.toBeInTheDocument();
  });

  it("derives user-facing cron status labels from runtime fields", async () => {
    setViewportMode(true);
    fixtures.jobs = [
      {
        id: "job-scheduled",
        name: "Scheduled job",
        schedule_type: "every",
        schedule: "300",
        prompt: "sync",
        enabled: true,
        next_run_ts: Math.floor(Date.now() / 1000) + 600,
        created_at: 0,
        updated_at: 10,
        last_run_ts: 0,
        last_success_ts: 0,
        failure_count: 0,
        last_error: "",
      },
      {
        id: "job-retrying",
        name: "Retrying job",
        schedule_type: "every",
        schedule: "300",
        prompt: "retry",
        enabled: true,
        next_run_ts: Math.floor(Date.now() / 1000) + 60,
        created_at: 0,
        updated_at: 9,
        last_run_ts: 1,
        last_success_ts: 0,
        failure_count: 2,
        last_error: "timeout",
      },
      {
        id: "job-paused",
        name: "Paused job",
        schedule_type: "every",
        schedule: "300",
        prompt: "pause",
        enabled: false,
        next_run_ts: 0,
        created_at: 0,
        updated_at: 8,
        last_run_ts: 1,
        last_success_ts: 0,
        failure_count: 0,
        last_error: "",
      },
      {
        id: "job-completed",
        name: "Completed job",
        schedule_type: "at",
        schedule: "2026-03-01T10:00:00Z",
        prompt: "once",
        enabled: false,
        next_run_ts: 0,
        created_at: 0,
        updated_at: 7,
        last_run_ts: 1,
        last_success_ts: 1,
        failure_count: 0,
        last_error: "",
      },
      {
        id: "job-failed",
        name: "Failed job",
        schedule_type: "every",
        schedule: "300",
        prompt: "fail",
        enabled: false,
        next_run_ts: 0,
        created_at: 0,
        updated_at: 6,
        last_run_ts: 1,
        last_success_ts: 0,
        failure_count: 3,
        last_error: "rate limited",
      },
    ];

    renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    expect(screen.getAllByText("Scheduled").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Retrying").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Paused").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
  });

  it("uses a drawer workflow for creating and editing cron jobs", async () => {
    setViewportMode(true);
    fixtures.jobs = [
      {
        id: "job-1",
        name: "Digest",
        schedule_type: "every",
        schedule: "300",
        prompt: "Build digest",
        enabled: true,
        next_run_ts: 1,
        created_at: 0,
        updated_at: 0,
        last_run_ts: 0,
        last_success_ts: 0,
        failure_count: 0,
        last_error: "",
      },
    ];

    renderPage();

    await waitFor(() => expect(apiMocks.listCronJobs).toHaveBeenCalled());

    fireEvent.click(screen.getAllByRole("button", { name: "New Job" })[0]);
    expect(screen.getByTestId("scheduler-job-editor")).toBeInTheDocument();
    expect(screen.getByText("Create Cron Job")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("scheduler-job-editor")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    expect(screen.getByText("Edit Cron Job")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Digest")).toBeInTheDocument();
  });
});
