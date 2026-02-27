import { ChatToolCall } from "@/lib/store";

type Props = {
  calls: ChatToolCall[];
};

export function ThoughtChain({ calls }: Props) {
  return (
    <details className="mt-3 rounded-xl border border-blue-100 bg-blue-50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">Tool Trace</summary>
      <div className="mt-2 space-y-2 text-xs">
        {calls.map((call, index) => (
          <div key={`${call.tool}-${index}`} className="rounded-md bg-white/70 p-2">
            <div className="font-semibold">{call.tool}</div>
            <div className="mt-1 break-all text-gray-600">
              input: {JSON.stringify(call.input ?? {}, null, 0)}
            </div>
            <div className="mt-1 break-all text-gray-600">
              output: {typeof call.output === "string" ? call.output : JSON.stringify(call.output ?? {})}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
