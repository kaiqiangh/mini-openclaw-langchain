"use client";

import dynamic from "next/dynamic";
import { memo } from "react";

import { ChatDebugEvent, ChatToolCall, RetrievalItem } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";

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
      className={`mb-3 rounded-md border p-3 text-sm ${
        role === "user"
          ? "ml-8 border-[var(--accent-strong)] bg-[var(--accent-soft)]"
          : "mr-8 border-[var(--border)] bg-[var(--surface-3)]"
      }`}
    >
      <div className="mb-2 flex items-center gap-2">
        <Badge tone={role === "user" ? "accent" : "neutral"}>{role}</Badge>
        <span className="ui-helper ui-mono">{role === "assistant" ? "agent-response" : "operator-input"}</span>
      </div>
      <div className="whitespace-pre-wrap break-words leading-6 text-[var(--text)]">{content}</div>
      {retrievals.length > 0 ? <RetrievalCard retrievals={retrievals} /> : null}
      {toolCalls.length > 0 ? <ThoughtChain calls={toolCalls} /> : null}
      {role === "assistant" && debugEvents.length > 0 ? <DebugTrace events={debugEvents} /> : null}
    </article>
  );
}

export const ChatMessage = memo(ChatMessageComponent);
