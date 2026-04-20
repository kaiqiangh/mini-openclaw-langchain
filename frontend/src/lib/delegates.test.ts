import { describe, expect, it } from "vitest";

import type { DelegateDetail, DelegateSummary } from "@/lib/api";
import {
  buildDelegateViewModels,
  shouldPollDelegates,
} from "@/lib/delegates";

const running: DelegateSummary = {
  delegate_id: "del_running",
  role: "researcher",
  task: "Summarize memory",
  status: "running",
  sub_session_id: "sub_running",
  created_at: 1,
};

const completed: DelegateSummary = {
  ...running,
  delegate_id: "del_done",
  status: "completed",
};

const completedDetail: DelegateDetail = {
  ...completed,
  agent_id: "default",
  parent_session_id: "sess_1",
  allowed_tools: ["read_files"],
  result_summary: "Delegate finished successfully.",
  steps_completed: 2,
  tools_used: ["read_files"],
  duration_ms: 1200,
};

describe("delegate helpers", () => {
  it("keeps polling after parent streaming stops while any delegate is still running", () => {
    expect(
      shouldPollDelegates({
        isStreaming: false,
        delegates: [running],
        detailById: {},
        hydrated: true,
      }),
    ).toBe(true);
  });

  it("keeps polling until terminal delegates have fetched detail", () => {
    expect(
      shouldPollDelegates({
        isStreaming: false,
        delegates: [completed],
        detailById: {},
        hydrated: true,
      }),
    ).toBe(true);
  });

  it("stops polling when delegates are terminal and detail is present", () => {
    expect(
      shouldPollDelegates({
        isStreaming: false,
        delegates: [completed],
        detailById: { [completed.delegate_id]: completedDetail },
        hydrated: true,
      }),
    ).toBe(false);
  });

  it("merges terminal detail onto delegate summaries by delegate id", () => {
    const viewModels = buildDelegateViewModels([completed], {
      [completed.delegate_id]: completedDetail,
    });

    expect(viewModels[0].detail?.result_summary).toBe(
      "Delegate finished successfully.",
    );
  });
});
