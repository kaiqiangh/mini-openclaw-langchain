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
      className="flex items-center gap-2 border-t border-[var(--border)] pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        const toSend = draft;
        setDraft("");
        void sendMessage(toSend);
      }}
    >
      <Input
        name="chat-message"
        aria-label="Chat message"
        autoComplete="off"
        className="w-full"
        placeholder={
          readOnly ? "Archived session (read-only)" : "Type a message…"
        }
        value={draft}
        disabled={isStreaming || readOnly}
        onChange={(event) => setDraft(event.target.value)}
      />
      <Button
        type="submit"
        variant="primary"
        className="min-w-[108px] px-3 text-sm"
        disabled={isStreaming || readOnly || draft.trim().length === 0}
      >
        {isStreaming ? "Streaming…" : "Send"}
      </Button>
    </form>
  );
}
