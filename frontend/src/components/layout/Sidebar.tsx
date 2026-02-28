"use client";

import { useState } from "react";

import { useAppStore } from "@/lib/store";
import {
  Badge,
  Button,
  Input,
  Select,
  TabButton,
  TabsList,
} from "@/components/ui/primitives";

export function Sidebar() {
  const [agentDraft, setAgentDraft] = useState("");
  const {
    agents,
    currentAgentId,
    setCurrentAgent,
    createAgentById,
    deleteAgentById,
    sessions,
    sessionsScope,
    currentSessionId,
    createNewSession,
    selectSession,
    setSessionsScope,
    archiveSessionById,
    restoreSessionById,
    deleteSessionById,
    initialized,
  } = useAppStore();

  return (
    <aside className="panel-shell flex min-h-0 flex-col">
      <div className="ui-panel-header">
        <h2 className="ui-panel-title">Agent Console</h2>
        <Badge tone={sessionsScope === "active" ? "success" : "warn"}>
          Scope: {sessionsScope === "active" ? "Active" : "Archived"}
        </Badge>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
        <div>
          <label className="ui-label" htmlFor="agent-selector">
            Agents
          </label>
          <Select
            id="agent-selector"
            name="agent-selector"
            className="mt-1 ui-mono text-xs"
            value={currentAgentId}
            onChange={(event) => {
              void setCurrentAgent(event.target.value);
            }}
          >
            {agents.map((agent) => (
              <option key={agent.agent_id} value={agent.agent_id}>
                {agent.agent_id} ({agent.active_sessions}/
                {agent.archived_sessions})
              </option>
            ))}
          </Select>
          <div className="mt-2 flex gap-1">
            <Input
              name="new-agent-id"
              aria-label="New agent id"
              autoComplete="off"
              spellCheck={false}
              className="min-w-0 flex-1 ui-mono text-xs"
              placeholder="new-agent-id…"
              value={agentDraft}
              onChange={(event) => setAgentDraft(event.target.value)}
            />
            <Button
              type="button"
              className="min-w-[64px] px-2 text-[11px]"
              disabled={!agentDraft.trim()}
              onClick={() => {
                const value = agentDraft.trim();
                setAgentDraft("");
                void createAgentById(value);
              }}
            >
              Create
            </Button>
            <Button
              type="button"
              variant="danger"
              className="min-w-[64px] px-2 text-[11px]"
              disabled={currentAgentId === "default"}
              onClick={() => {
                void deleteAgentById(currentAgentId);
              }}
            >
              Delete
            </Button>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <h2 className="ui-panel-title">Sessions</h2>
          <Button
            type="button"
            className="px-3 text-[11px]"
            disabled={sessionsScope !== "active"}
            onClick={() => {
              void createNewSession();
            }}
          >
            New
          </Button>
        </div>

        <TabsList className="mb-1">
          <TabButton
            type="button"
            active={sessionsScope === "active"}
            onClick={() => {
              void setSessionsScope("active");
            }}
          >
            Active
          </TabButton>
          <TabButton
            type="button"
            active={sessionsScope === "archived"}
            onClick={() => {
              void setSessionsScope("archived");
            }}
          >
            Archived
          </TabButton>
          <div className="flex items-center justify-center">
            <Badge tone="neutral">{sessions.length} items</Badge>
          </div>
        </TabsList>

        {!initialized ? (
          <div className="ui-status" aria-live="polite">
            Loading…
          </div>
        ) : (
          <ul className="ui-scroll-area space-y-2 pr-1">
            {sessions.map((session) => (
              <li key={session.session_id}>
                <div
                  className={`rounded-md border p-2 text-xs transition-colors duration-200 ${
                    session.session_id === currentSessionId
                      ? "border-[var(--accent-strong)] bg-[var(--accent-soft)]"
                      : "border-[var(--border)] bg-[var(--surface-3)] hover:border-[var(--border-strong)]"
                  }`}
                >
                  <button
                    className="w-full text-left"
                    onClick={() => {
                      void selectSession(session.session_id);
                    }}
                  >
                    <div className="truncate font-semibold text-[var(--text)]">
                      {session.title || "New Session"}
                    </div>
                    <div className="ui-mono mt-1 text-[11px] text-[var(--muted)]">
                      {session.session_id.slice(0, 8)}
                    </div>
                  </button>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {sessionsScope === "active" ? (
                      <>
                        <Button
                          type="button"
                          className="min-h-[28px] px-2 text-[10px]"
                          onClick={() => {
                            void archiveSessionById(session.session_id);
                          }}
                        >
                          Archive
                        </Button>
                        <Button
                          type="button"
                          variant="danger"
                          className="min-h-[28px] px-2 text-[10px]"
                          onClick={() => {
                            void deleteSessionById(session.session_id, false);
                          }}
                        >
                          Delete
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button
                          type="button"
                          className="min-h-[28px] px-2 text-[10px]"
                          onClick={() => {
                            void restoreSessionById(session.session_id);
                          }}
                        >
                          Restore
                        </Button>
                        <Button
                          type="button"
                          variant="danger"
                          className="min-h-[28px] px-2 text-[10px]"
                          onClick={() => {
                            void deleteSessionById(session.session_id, true);
                          }}
                        >
                          Delete
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {initialized && sessions.length === 0 ? (
          <div className="ui-empty">
            <strong>No Sessions</strong>
            <span>
              {sessionsScope === "active"
                ? "Create a new session to begin."
                : "No archived sessions."}
            </span>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
