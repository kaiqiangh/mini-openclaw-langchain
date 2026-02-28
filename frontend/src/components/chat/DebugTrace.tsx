import { ChatDebugEvent } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";

type Props = {
  events: ChatDebugEvent[];
};

function summarize(data: unknown): string {
  try {
    const text = typeof data === "string" ? data : JSON.stringify(data);
    return text.length > 240 ? `${text.slice(0, 240)}…` : text;
  } catch {
    return String(data);
  }
}

function pretty(data: unknown): string {
  try {
    if (typeof data === "string") {
      return data;
    }
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

export function DebugTrace({ events }: Props) {
  return (
    <details className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm">
      <summary className="cursor-pointer font-medium text-[var(--text)]">
        Agent Debug Trace
      </summary>
      <div className="mt-2 space-y-2 text-xs">
        {events.map((event) => (
          <div
            key={event.id}
            className="rounded border border-[var(--border)] bg-[var(--surface-2)] p-2"
          >
            <div className="flex items-center justify-between gap-2">
              <Badge tone="neutral">{event.type}</Badge>
              <span className="ui-mono text-[10px] text-[var(--muted)]">
                {new Date(event.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <div className="mt-1 break-all text-[var(--muted)]">
              {summarize(event.data)}
            </div>
            <pre className="ui-mono mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded border border-[var(--border)] bg-[var(--surface-3)] p-2 text-[11px] text-[var(--text)]">
              {pretty(event.data)}
            </pre>
          </div>
        ))}
      </div>
    </details>
  );
}
