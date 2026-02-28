import type { PointerEvent } from "react";

export function ResizeHandle({
  onPointerDown,
  dragging = false,
}: {
  onPointerDown?: (event: PointerEvent<HTMLButtonElement>) => void;
  dragging?: boolean;
}) {
  return (
    <button
      type="button"
      className="ui-split-handle"
      onPointerDown={onPointerDown}
      aria-label="Resize panels"
      data-dragging={dragging ? "true" : "false"}
    />
  );
}
