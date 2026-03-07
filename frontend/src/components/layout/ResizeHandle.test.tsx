import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { ResizeHandle } from "@/components/layout/ResizeHandle";

describe("ResizeHandle", () => {
  it("exposes separator semantics and supports keyboard stepping", () => {
    const onStep = vi.fn();

    render(
      <ResizeHandle
        {...({
          dragging: false,
          valueNow: 320,
          valueMin: 260,
          valueMax: 520,
          onStep,
        } as any)}
      />,
    );

    const handle = screen.getByRole("separator", { name: "Resize panels" });
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });

    expect(handle).toHaveAttribute("aria-orientation", "vertical");
    expect(handle).toHaveAttribute("aria-valuenow", "320");
    expect(handle).toHaveAttribute("aria-valuemin", "260");
    expect(handle).toHaveAttribute("aria-valuemax", "520");
    expect(onStep).toHaveBeenNthCalledWith(1, -1);
    expect(onStep).toHaveBeenNthCalledWith(2, 1);
  });
});
