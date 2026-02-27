import { ChatDebugEvent } from "@/lib/store";

type Props = {
  events: ChatDebugEvent[];
};

function summarize(data: unknown): string {
  try {
    const text = typeof data === "string" ? data : JSON.stringify(data);
    return text.length > 240 ? `${text.slice(0, 240)}...` : text;
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
    <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">Agent Debug Trace</summary>
      <div className="mt-2 space-y-2 text-xs">
        {events.map((event) => (
          <div key={event.id} className="rounded-md bg-white/80 p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold">{event.type}</span>
              <span className="text-[10px] text-gray-500">
                {new Date(event.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <div className="mt-1 break-all text-gray-600">{summarize(event.data)}</div>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-100 p-2 text-[11px] text-slate-700">
              {pretty(event.data)}
            </pre>
          </div>
        ))}
      </div>
    </details>
  );
}
