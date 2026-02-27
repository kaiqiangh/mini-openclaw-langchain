import { ChatToolCall } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";

type Props = {
  calls: ChatToolCall[];
};

export function ThoughtChain({ calls }: Props) {
  return (
    <details className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm">
      <summary className="cursor-pointer font-medium text-[var(--text)]">Tool Trace</summary>
      <div className="mt-2 space-y-2 text-xs">
        {calls.map((call, index) => (
          <div key={`${call.tool}-${index}`} className="rounded border border-[var(--border)] bg-[var(--surface-2)] p-2">
            <div className="flex items-center gap-2">
              <Badge tone="accent">{call.tool}</Badge>
            </div>
            <div className="ui-mono mt-1 break-all text-[var(--muted)]">
              input: {JSON.stringify(call.input ?? {}, null, 0)}
            </div>
            <div className="ui-mono mt-1 break-all text-[var(--muted)]">
              output: {typeof call.output === "string" ? call.output : JSON.stringify(call.output ?? {})}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
