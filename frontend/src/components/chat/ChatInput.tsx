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
      className="ui-composer space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const toSend = draft;
        if (!toSend.trim()) return;
        const sent = await sendMessage(toSend);
        if (sent) {
          setDraft("");
        }
      }}
    >
      <div className="ui-composer-row">
        <Input
          name="chat-message"
          aria-label="Chat message"
          autoComplete="off"
          className="w-full flex-1"
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
          className="min-w-[132px] px-4 text-sm"
          disabled={readOnly || draft.trim().length === 0}
        >
          {isStreaming ? "Streaming…" : "Send"}
        </Button>
      </div>
      <div id="chat-input-hint" className="ui-helper">
        {readOnly
          ? "Archived sessions are read-only."
          : "Press Enter to send. Use Sessions to switch between live and archived transcripts."}
      </div>
    </form>
  );
}
