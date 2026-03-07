import type { PointerEvent } from "react";

export function ResizeHandle({
  onPointerDown,
  onStep,
  dragging = false,
  valueNow,
  valueMin,
  valueMax,
  ariaLabel = "Resize panels",
}: {
  onPointerDown?: (event: PointerEvent<HTMLDivElement>) => void;
  onStep?: (direction: -1 | 1) => void;
  dragging?: boolean;
  valueNow?: number;
  valueMin?: number;
  valueMax?: number;
  ariaLabel?: string;
}) {
  return (
    <div
      className="ui-split-handle"
      role="separator"
      tabIndex={0}
      onPointerDown={onPointerDown}
      onKeyDown={(event) => {
        if (!onStep) return;
        if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          event.preventDefault();
          onStep(-1);
        }
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          event.preventDefault();
          onStep(1);
        }
      }}
      aria-label={ariaLabel}
      aria-orientation="vertical"
      aria-valuenow={typeof valueNow === "number" ? Math.round(valueNow) : undefined}
      aria-valuemin={typeof valueMin === "number" ? Math.round(valueMin) : undefined}
      aria-valuemax={typeof valueMax === "number" ? Math.round(valueMax) : undefined}
      data-dragging={dragging ? "true" : "false"}
    />
  );
}
