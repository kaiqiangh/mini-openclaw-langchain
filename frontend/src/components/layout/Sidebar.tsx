"use client";

import { useState } from "react";

import { useAppStore } from "@/lib/store";
import {
  Badge,
  Button,
  EmptyState,
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
              size="sm"
              className="min-w-[72px] px-2"
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
              size="sm"
              className="min-w-[72px] px-2"
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
            size="sm"
            className="px-3"
            disabled={sessionsScope !== "active"}
            onClick={() => {
              void createNewSession();
            }}
          >
            New
          </Button>
        </div>

        <div className="mb-1 flex items-center justify-between gap-2">
          <TabsList
            className="flex-1 grid-cols-2"
            ariaLabel="Session scope"
            value={sessionsScope}
            onChange={(value) => {
              void setSessionsScope(value as "active" | "archived");
            }}
          >
            <TabButton
              id="sessions-tab-active"
              controls="sessions-panel-active"
              value="active"
            >
              Active
            </TabButton>
            <TabButton
              id="sessions-tab-archived"
              controls="sessions-panel-archived"
              value="archived"
            >
              Archived
            </TabButton>
          </TabsList>
          <Badge tone="neutral">{sessions.length} items</Badge>
        </div>

        {!initialized ? (
          <div className="ui-status" aria-live="polite">
            Loading…
          </div>
        ) : (
          <div
            id={
              sessionsScope === "active"
                ? "sessions-panel-active"
                : "sessions-panel-archived"
            }
            role="tabpanel"
            aria-labelledby={
              sessionsScope === "active"
                ? "sessions-tab-active"
                : "sessions-tab-archived"
            }
            className="min-h-0 flex-1"
          >
            <ul className="ui-scroll-area space-y-2 pr-1">
              {sessions.map((session) => (
                <li key={session.session_id}>
                  <div
                    className={`rounded-md border p-3 text-sm transition-colors duration-200 ${
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
                      <div className="ui-mono mt-1 text-xs text-[var(--muted)]">
                        {session.session_id.slice(0, 8)}
                      </div>
                    </button>
                    <div className="mt-3 flex flex-wrap gap-1">
                      {sessionsScope === "active" ? (
                        <>
                          <Button
                            type="button"
                            size="sm"
                            onClick={() => {
                              void archiveSessionById(session.session_id);
                            }}
                          >
                            Archive
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="danger"
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
                            size="sm"
                            onClick={() => {
                              void restoreSessionById(session.session_id);
                            }}
                          >
                            Restore
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="danger"
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
          </div>
        )}
        {initialized && sessions.length === 0 ? (
          <EmptyState
            title="No Sessions"
            description={
              sessionsScope === "active"
                ? "Create a new session to begin."
                : "No archived sessions."
            }
          />
        ) : null}
      </div>
    </aside>
  );
}
