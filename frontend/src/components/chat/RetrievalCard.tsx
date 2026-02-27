import { RetrievalItem } from "@/lib/store";

type Props = {
  retrievals: RetrievalItem[];
};

export function RetrievalCard({ retrievals }: Props) {
  return (
    <details className="mt-3 rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">RAG Retrieval</summary>
      <div className="mt-2 space-y-2 text-xs">
        {retrievals.map((item, index) => (
          <div key={`${item.source}-${index}`} className="rounded-md bg-white/70 p-2">
            <div className="font-semibold">{item.source}</div>
            <div className="text-[11px] text-gray-500">score: {item.score}</div>
            <div className="mt-1 whitespace-pre-wrap text-gray-600">{item.text}</div>
          </div>
        ))}
      </div>
    </details>
  );
}
