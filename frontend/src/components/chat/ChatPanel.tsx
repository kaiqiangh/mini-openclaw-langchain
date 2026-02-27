"use client";

import { useEffect, useMemo, useRef } from "react";

import { useAppStore } from "@/lib/store";
import { Badge, EmptyState } from "@/components/ui/primitives";

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
    <section className="panel-shell flex min-h-0 flex-col">
      <div className="ui-panel-header">
        <h2 className="ui-panel-title">Agent Log</h2>
        {isStreaming ? <Badge tone="accent">Running</Badge> : <Badge tone="success">Ready</Badge>}
      </div>

      <div ref={scrollRef} className="ui-scroll-area mb-3 flex-1 px-4 pt-4">
        {messages.length === 0 ? (
          <EmptyState
            title={sessionsScope === "archived" ? "Read-only Session" : "No Messages"}
            description={
              sessionsScope === "archived"
                ? "Archived sessions are read-only."
                : "Send a message to start the session."
            }
          />
        ) : (
          renderedMessages
        )}
      </div>

      <div className="px-4 pb-4">
        {isStreaming ? (
          <div className="ui-status mb-2 text-[var(--accent-strong)]" aria-live="polite">
            Streaming response…
          </div>
        ) : null}
        {error ? (
          <div className="ui-status mb-2 text-[var(--danger)]" aria-live="polite">
            {error}
          </div>
        ) : null}
        <ChatInput />
      </div>
    </section>
  );
}
