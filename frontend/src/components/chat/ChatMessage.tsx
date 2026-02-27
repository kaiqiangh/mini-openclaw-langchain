"use client";

import dynamic from "next/dynamic";
import { memo } from "react";

import { ChatDebugEvent, ChatToolCall, RetrievalItem } from "@/lib/store";

const RetrievalCard = dynamic(
  () => import("./RetrievalCard").then((mod) => mod.RetrievalCard),
  { ssr: false },
);

const ThoughtChain = dynamic(
  () => import("./ThoughtChain").then((mod) => mod.ThoughtChain),
  { ssr: false },
);
const DebugTrace = dynamic(
  () => import("./DebugTrace").then((mod) => mod.DebugTrace),
  { ssr: false },
);

type Props = {
  role: "user" | "assistant";
  content: string;
  toolCalls: ChatToolCall[];
  retrievals: RetrievalItem[];
  debugEvents: ChatDebugEvent[];
};

function ChatMessageComponent({ role, content, toolCalls, retrievals, debugEvents }: Props) {
  return (
    <article
      className={`mb-3 rounded-xl border p-3 text-sm ${
        role === "user"
          ? "ml-8 border-blue-200/70 bg-blue-50/85"
          : "mr-8 border-gray-200/80 bg-white/92"
      }`}
    >
      <div className="mb-1 text-[11px] uppercase text-gray-500">{role}</div>
      <div className="whitespace-pre-wrap leading-6">{content}</div>
      {retrievals.length > 0 ? <RetrievalCard retrievals={retrievals} /> : null}
      {toolCalls.length > 0 ? <ThoughtChain calls={toolCalls} /> : null}
      {role === "assistant" && debugEvents.length > 0 ? <DebugTrace events={debugEvents} /> : null}
    </article>
  );
}

export const ChatMessage = memo(ChatMessageComponent);
