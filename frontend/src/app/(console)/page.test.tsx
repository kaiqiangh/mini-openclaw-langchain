import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import Home from "@/app/(console)/page";

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

  it("matches right splitter keyboard behavior to drag semantics", () => {
    const { container } = render(<Home />);
    const desktopGrid = container.querySelector(".grid");

    if (!(desktopGrid instanceof HTMLElement)) {
      throw new Error("desktop grid not found");
    }

    Object.defineProperty(desktopGrid, "getBoundingClientRect", {
      value: () =>
        ({
          width: 1400,
          height: 800,
          top: 0,
          left: 0,
          right: 1400,
          bottom: 800,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) satisfies DOMRect,
      configurable: true,
    });

    const handles = screen.getAllByRole("separator", { name: "Resize panels" });
    const rightHandle = handles[1];

    expect(rightHandle).toHaveAttribute("aria-valuenow", "360");

    fireEvent.keyDown(rightHandle, { key: "ArrowLeft" });
    expect(rightHandle).toHaveAttribute("aria-valuenow", "392");

    fireEvent.keyDown(rightHandle, { key: "ArrowRight" });
    expect(rightHandle).toHaveAttribute("aria-valuenow", "360");
  });
});
