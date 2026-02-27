"use client";

import { useState } from "react";

import { useAppStore } from "@/lib/store";

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
    <aside className="panel-shell flex min-h-0 flex-col p-4">
      <div className="mb-4">
        <h2 className="mb-2 text-sm font-semibold">Agents</h2>
        <select
          className="w-full rounded-lg border border-gray-300 bg-white px-2 py-2 text-xs"
          value={currentAgentId}
          onChange={(event) => {
            void setCurrentAgent(event.target.value);
          }}
        >
          {agents.map((agent) => (
            <option key={agent.agent_id} value={agent.agent_id}>
              {agent.agent_id} ({agent.active_sessions}/{agent.archived_sessions})
            </option>
          ))}
        </select>
        <div className="mt-2 flex gap-1">
          <input
            className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1 text-[11px]"
            placeholder="new-agent-id"
            value={agentDraft}
            onChange={(event) => setAgentDraft(event.target.value)}
          />
          <button
            className="rounded border border-gray-300 bg-white px-2 py-1 text-[10px]"
            disabled={!agentDraft.trim()}
            onClick={() => {
              const value = agentDraft.trim();
              setAgentDraft("");
              void createAgentById(value);
            }}
          >
            Create
          </button>
          <button
            className="rounded border border-red-300 bg-red-50 px-2 py-1 text-[10px] text-red-700"
            disabled={currentAgentId === "default"}
            onClick={() => {
              void deleteAgentById(currentAgentId);
            }}
          >
            Delete
          </button>
        </div>
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Sessions</h2>
        <button
          className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-xs"
          disabled={sessionsScope !== "active"}
          onClick={() => {
            void createNewSession();
          }}
        >
          New
        </button>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2">
        <button
          className={`rounded-lg border px-2 py-1 text-xs ${
            sessionsScope === "active" ? "border-blue-400 bg-blue-50 text-blue-700" : "border-gray-300 bg-white"
          }`}
          onClick={() => {
            void setSessionsScope("active");
          }}
        >
          Active
        </button>
        <button
          className={`rounded-lg border px-2 py-1 text-xs ${
            sessionsScope === "archived" ? "border-blue-400 bg-blue-50 text-blue-700" : "border-gray-300 bg-white"
          }`}
          onClick={() => {
            void setSessionsScope("archived");
          }}
        >
          Archived
        </button>
      </div>

      {!initialized ? (
        <p className="text-xs text-gray-500">Loading...</p>
      ) : (
        <ul className="space-y-1 overflow-auto">
          {sessions.map((session) => (
            <li key={session.session_id}>
              <div
                className={`w-full rounded-lg px-2 py-2 text-left text-xs ${
                  session.session_id === currentSessionId
                    ? "bg-blue-100 text-blue-700"
                    : "hover:bg-gray-100"
                }`}
              >
                <button
                  className="w-full text-left"
                  onClick={() => {
                    void selectSession(session.session_id);
                  }}
                >
                  <div className="truncate font-medium">{session.title || "New Session"}</div>
                  <div className="text-[10px] text-gray-500">{session.session_id.slice(0, 8)}</div>
                </button>
                <div className="mt-2 flex gap-1">
                  {sessionsScope === "active" ? (
                    <>
                      <button
                        className="rounded border border-gray-300 bg-white px-2 py-1 text-[10px]"
                        onClick={() => {
                          void archiveSessionById(session.session_id);
                        }}
                      >
                        Archive
                      </button>
                      <button
                        className="rounded border border-red-300 bg-red-50 px-2 py-1 text-[10px] text-red-700"
                        onClick={() => {
                          void deleteSessionById(session.session_id, false);
                        }}
                      >
                        Delete
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="rounded border border-gray-300 bg-white px-2 py-1 text-[10px]"
                        onClick={() => {
                          void restoreSessionById(session.session_id);
                        }}
                      >
                        Restore
                      </button>
                      <button
                        className="rounded border border-red-300 bg-red-50 px-2 py-1 text-[10px] text-red-700"
                        onClick={() => {
                          void deleteSessionById(session.session_id, true);
                        }}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
