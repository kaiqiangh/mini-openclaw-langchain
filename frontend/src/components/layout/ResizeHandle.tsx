export function ResizeHandle() {
  return (
    <div
      className="h-full w-2 cursor-col-resize rounded bg-[var(--surface-header)] transition-colors duration-150 hover:bg-[var(--border-strong)]"
      aria-hidden
    />
  );
}
