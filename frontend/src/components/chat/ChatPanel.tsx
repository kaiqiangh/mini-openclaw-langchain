"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useAppStore } from "@/lib/store";
import { Badge, Button, EmptyState } from "@/components/ui/primitives";

import { ChatInput } from "./ChatInput";
import { ChatMessage } from "./ChatMessage";

export function ChatPanel() {
  const AGENT_LOG_EXPANDED_KEY = "mini-openclaw:agent-log-expanded:v1";
  const {
    messages,
    error,
    isStreaming,
    sessionsScope,
    maxStepsPrompt,
    continueAfterMaxSteps,
    cancelAfterMaxSteps,
  } = useAppStore();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(AGENT_LOG_EXPANDED_KEY);
    if (raw === "0") {
      setExpanded(false);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(AGENT_LOG_EXPANDED_KEY, expanded ? "1" : "0");
  }, [expanded]);

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
    <section className="panel-shell flex min-h-0 min-w-0 flex-col">
      <div className="ui-panel-header">
        <h2 className="ui-panel-title">Agent Log</h2>
        <div className="flex items-center gap-2">
          {isStreaming ? (
            <Badge tone="accent">Running</Badge>
          ) : (
            <Badge tone="success">Ready</Badge>
          )}
          <Button
            type="button"
            size="sm"
            className="px-3"
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
            aria-controls="agent-log-content"
          >
            {expanded ? "Collapse" : "Expand"}
          </Button>
        </div>
      </div>

      <div
        id="agent-log-content"
        hidden={!expanded}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div
          ref={scrollRef}
          className="ui-scroll-area mb-3 flex-1 px-3 pt-3 sm:px-4 sm:pt-4"
        >
          {messages.length === 0 ? (
            <EmptyState
              title={
                sessionsScope === "archived" ? "Read-only Session" : "No Messages"
              }
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
            <div
              className="ui-status mb-2 text-[var(--accent-strong)]"
              aria-live="polite"
            >
              Streaming response…
            </div>
          ) : null}
          {maxStepsPrompt ? (
            <div className="ui-alert mb-2" role="alert">
              <div className="font-medium">Agent reached max_steps.</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    void continueAfterMaxSteps();
                  }}
                >
                  Continue
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => {
                    void cancelAfterMaxSteps();
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}
          {error ? (
            <div className="ui-alert mb-2" aria-live="polite" role="alert">
              {error}
            </div>
          ) : null}
          <ChatInput />
        </div>
      </div>

      {!expanded ? (
        <div className="px-4 py-3 text-sm text-[var(--muted)]">
          Agent log is collapsed.
        </div>
      ) : null}
    </section>
  );
}
