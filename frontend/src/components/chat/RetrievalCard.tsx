import { RetrievalItem } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";

type Props = {
  retrievals: RetrievalItem[];
};

export function RetrievalCard({ retrievals }: Props) {
  return (
    <details className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-sm">
      <summary className="cursor-pointer font-medium text-[var(--text)]">
        RAG Retrieval
      </summary>
      <div className="mt-2 space-y-2 text-xs">
        {retrievals.map((item, index) => (
          <div
            key={`${item.source}-${index}`}
            className="rounded border border-[var(--border)] bg-[var(--surface-2)] p-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <div className="ui-mono break-all font-semibold text-[var(--text)]">
                {item.source}
              </div>
              <Badge tone="accent">{`score ${item.score}`}</Badge>
            </div>
            <div className="mt-1 whitespace-pre-wrap break-words text-[var(--muted)]">
              {item.text}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
