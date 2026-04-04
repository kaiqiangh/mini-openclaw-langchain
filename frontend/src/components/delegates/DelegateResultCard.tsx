import { useState } from "react";
import { type DelegateDetail } from "@/lib/api";

interface Props {
  delegate: DelegateDetail;
}

export function DelegateResultCard({ delegate }: Props) {
  const [expanded, setExpanded] = useState(false);
  if (delegate.status === "running") return null;

  const isError = delegate.status === "failed" || delegate.status === "timeout";

  return (
    <div className="ui-panel my-2" data-testid="delegate-result-card">
      <button
        type="button"
        className="ui-panel-header w-full cursor-pointer text-left hover:bg-[var(--surface-header)]/80"
        onClick={() => setExpanded((p) => !p)}
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-3">
          <span className="text-xs uppercase tracking-wide text-[var(--muted-soft)]">
            {delegate.role}
          </span>
          {isError ? (
            <span className="text-xs text-[var(--danger)]">{delegate.error_message}</span>
          ) : (
            <span className="text-xs text-[var(--success)]">
              {delegate.result_summary?.slice(0, 120)}...
            </span>
          )}
          <span className="ml-auto text-xs text-[var(--muted-soft)]">
            {delegate.duration_ms ? `${(delegate.duration_ms / 1000).toFixed(1)}s` : ""}
            {delegate.steps_completed ? ` · ${delegate.steps_completed} steps` : ""}
          </span>
        </div>
      </button>
      {expanded && delegate.result_summary && (
        <div className="p-4 pt-3">
          <div className="ui-scroll-area max-h-[400px] whitespace-pre-wrap text-sm text-[var(--text)]">
            {delegate.result_summary}
          </div>
          {delegate.tools_used && delegate.tools_used.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {delegate.tools_used.map((t) => (
                <span key={t} className="ui-badge ui-badge-neutral text-xs">{t}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
