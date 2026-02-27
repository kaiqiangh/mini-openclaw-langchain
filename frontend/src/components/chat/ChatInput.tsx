"use client";

import { useState } from "react";

import { useAppStore } from "@/lib/store";

export function ChatInput() {
  const { sendMessage, isStreaming, sessionsScope } = useAppStore();
  const [draft, setDraft] = useState("");
  const readOnly = sessionsScope === "archived";

  return (
    <form
      className="flex items-center gap-2 border-t border-gray-200 pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        const toSend = draft;
        setDraft("");
        void sendMessage(toSend);
      }}
    >
      <input
        className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm"
        placeholder={readOnly ? "Archived session (read-only)" : "Type a message..."}
        value={draft}
        disabled={isStreaming || readOnly}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button
        className="rounded-xl bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-60"
        disabled={isStreaming || readOnly || draft.trim().length === 0}
      >
        {isStreaming ? "Streaming..." : "Send"}
      </button>
    </form>
  );
}
