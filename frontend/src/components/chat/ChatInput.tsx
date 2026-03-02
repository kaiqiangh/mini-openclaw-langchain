"use client";

import { useState } from "react";

import { useAppStore } from "@/lib/store";
import { Button, Input } from "@/components/ui/primitives";

export function ChatInput() {
  const { sendMessage, isStreaming, sessionsScope } = useAppStore();
  const [draft, setDraft] = useState("");
  const readOnly = sessionsScope === "archived";

  return (
    <form
      className="space-y-2 border-t border-[var(--border)] pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        const toSend = draft;
        setDraft("");
        void sendMessage(toSend);
      }}
    >
      <div className="flex items-center gap-2">
        <Input
          name="chat-message"
          aria-label="Chat message"
          autoComplete="off"
          className="w-full"
          hintId="chat-input-hint"
          placeholder={
            readOnly ? "Archived session (read-only)" : "Type a message…"
          }
          value={draft}
          disabled={isStreaming || readOnly}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          type="submit"
          size="lg"
          variant="primary"
          loading={isStreaming}
          className="min-w-[116px] px-3 text-sm"
          disabled={readOnly || draft.trim().length === 0}
        >
          {isStreaming ? "Streaming…" : "Send"}
        </Button>
      </div>
      <div id="chat-input-hint" className="ui-helper">
        {readOnly
          ? "Archived sessions are read-only."
          : "Press Enter to send."}
      </div>
    </form>
  );
}
