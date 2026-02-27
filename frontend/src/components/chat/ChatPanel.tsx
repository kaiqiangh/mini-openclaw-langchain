"use client";

import { useEffect, useMemo, useRef } from "react";

import { useAppStore } from "@/lib/store";

import { ChatInput } from "./ChatInput";
import { ChatMessage } from "./ChatMessage";

export function ChatPanel() {
  const { messages, error, isStreaming, sessionsScope } = useAppStore();
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const renderedMessages = useMemo(
    () =>
      messages.map((msg) => (
        <ChatMessage
          key={msg.id}
          role={msg.role}
          content={msg.content}
          toolCalls={msg.toolCalls}
          retrievals={msg.retrievals}
          debugEvents={msg.debugEvents}
        />
      )),
    [messages],
  );

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, isStreaming]);

  return (
    <section className="panel-shell flex min-h-0 flex-col p-4">
      <div ref={scrollRef} className="mb-4 flex-1 overflow-auto">
        {messages.length === 0 ? (
          <div className="text-sm text-gray-500">
            {sessionsScope === "archived"
              ? "Archived sessions are read-only."
              : "Send a message to start the session."}
          </div>
        ) : (
          renderedMessages
        )}
        {isStreaming ? <div className="mt-2 text-xs text-blue-600">Streaming response...</div> : null}
      </div>
      {error ? <div className="mb-2 text-xs text-red-600">{error}</div> : null}
      <ChatInput />
    </section>
  );
}
