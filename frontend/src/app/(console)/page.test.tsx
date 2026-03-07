import React from "react";
import { render, screen } from "@testing-library/react";

import Home from "@/app/page";

vi.mock("@/components/layout/Sidebar", () => ({
  Sidebar: () => <div>sidebar</div>,
}));

vi.mock("@/components/chat/ChatPanel", () => ({
  ChatPanel: () => <div>chat</div>,
}));

vi.mock("@/components/editor/InspectorPanel", () => ({
  InspectorPanel: () => <div>inspector</div>,
}));

describe("workspace split layout", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the agents console without the middle chat panel", () => {
    const { container } = render(<Home />);

    expect(screen.getAllByText("sidebar").length).toBeGreaterThan(0);
    expect(screen.getAllByText("inspector").length).toBeGreaterThan(0);
    expect(screen.queryByText("chat")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Chat" }),
    ).not.toBeInTheDocument();

    expect(
      container.querySelectorAll('[role="separator"][aria-label="Resize panels"]'),
    ).toHaveLength(1);
  });
});
