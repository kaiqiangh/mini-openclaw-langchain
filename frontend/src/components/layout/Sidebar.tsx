"use client";

import { useEffect, useMemo, useState } from "react";

import {
  AgentToolCatalog,
  AgentToolItem,
  getAgentTools,
  setAgentToolSelection,
  ToolSelectionTrigger,
} from "@/lib/api";
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

type ToolStatusFilter = "all" | "enabled" | "disabled";
type SidebarSectionKey = "agents" | "tools";

const SIDEBAR_SECTION_STATE_KEY = "mini-openclaw:sidebar-sections:v1";
const DEFAULT_SECTIONS: Record<SidebarSectionKey, boolean> = {
  agents: true,
  tools: true,
};

function inferToolCategory(toolName: string): string {
  if (toolName.startsWith("scheduler_")) return "Scheduler";
  if (toolName.startsWith("session")) return "Sessions";
  if (toolName.includes("knowledge")) return "Knowledge";
  if (toolName.includes("web") || toolName.includes("fetch")) return "Web";
  if (toolName.includes("read") || toolName.includes("pdf")) return "Files";
  if (toolName.includes("terminal") || toolName.includes("python")) return "Execution";
  if (toolName.includes("agent")) return "Agents";
  return "Core";
}

export function Sidebar() {
  const [agentDraft, setAgentDraft] = useState("");
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [toolCatalog, setToolCatalog] = useState<AgentToolCatalog | null>(null);
  const [toolTrigger, setToolTrigger] = useState<ToolSelectionTrigger>("chat");
  const [toolQuery, setToolQuery] = useState("");
  const [toolStatusFilter, setToolStatusFilter] =
    useState<ToolStatusFilter>("all");
  const [toolCategoryFilter, setToolCategoryFilter] = useState("all");
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsSaving, setToolsSaving] = useState(false);
  const [toolsStatus, setToolsStatus] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkStatus, setBulkStatus] = useState("");
  const [sections, setSections] =
    useState<Record<SidebarSectionKey, boolean>>(DEFAULT_SECTIONS);
  const {
    agents,
    currentAgentId,
    setCurrentAgent,
    createAgentById,
    deleteAgentById,
    bulkDeleteAgents,
    bulkExportAgents,
  } = useAppStore();

  useEffect(() => {
    setSelectedAgentIds((previous) =>
      previous.filter((agentId) =>
        agents.some((item) => item.agent_id === agentId),
      ),
    );
  }, [agents]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(SIDEBAR_SECTION_STATE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<Record<SidebarSectionKey, boolean>>;
      setSections({
        agents: parsed.agents ?? true,
        tools: parsed.tools ?? true,
      });
    } catch {
      setSections(DEFAULT_SECTIONS);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(SIDEBAR_SECTION_STATE_KEY, JSON.stringify(sections));
  }, [sections]);

  useEffect(() => {
    let cancelled = false;
    setToolsLoading(true);
    setToolsStatus("");
    void getAgentTools(currentAgentId)
      .then((catalog) => {
        if (cancelled) return;
        setToolCatalog(catalog);
      })
      .catch((error) => {
        if (cancelled) return;
        setToolCatalog(null);
        setToolsStatus(
          error instanceof Error ? error.message : "Failed to load tools",
        );
      })
      .finally(() => {
        if (cancelled) return;
        setToolsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentAgentId]);

  const selectedToolNames = useMemo(
    () => new Set(toolCatalog?.enabled_tools[toolTrigger] ?? []),
    [toolCatalog, toolTrigger],
  );

  const toolCategories = useMemo(() => {
    const values = new Set<string>();
    for (const item of toolCatalog?.tools ?? []) {
      values.add(inferToolCategory(item.name));
    }
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }, [toolCatalog]);

  useEffect(() => {
    if (toolCategoryFilter === "all") return;
    if (toolCategories.includes(toolCategoryFilter)) return;
    setToolCategoryFilter("all");
  }, [toolCategories, toolCategoryFilter]);

  const filteredTools = useMemo(() => {
    const q = toolQuery.trim().toLowerCase();
    return (toolCatalog?.tools ?? []).filter((tool) => {
      const state = tool.trigger_status[toolTrigger];
      const category = inferToolCategory(tool.name);
      if (toolCategoryFilter !== "all" && category !== toolCategoryFilter) {
        return false;
      }
      if (toolStatusFilter === "enabled" && !state.enabled) return false;
      if (toolStatusFilter === "disabled" && state.enabled) return false;
      if (!q) return true;
      return (
        tool.name.toLowerCase().includes(q) ||
        tool.description.toLowerCase().includes(q) ||
        category.toLowerCase().includes(q)
      );
    });
  }, [toolCatalog, toolCategoryFilter, toolQuery, toolStatusFilter, toolTrigger]);

  const groupedTools = useMemo(() => {
    const map = new Map<string, AgentToolItem[]>();
    for (const tool of filteredTools) {
      const key = inferToolCategory(tool.name);
      const rows = map.get(key) ?? [];
      rows.push(tool);
      map.set(key, rows);
    }
    return Array.from(map.entries()).sort(([left], [right]) =>
      left.localeCompare(right),
    );
  }, [filteredTools]);

  async function toggleToolSelection(toolName: string) {
    if (!toolCatalog || toolsSaving) return;
    const current = new Set(selectedToolNames);
    if (current.has(toolName)) {
      current.delete(toolName);
    } else {
      current.add(toolName);
    }
    setToolsSaving(true);
    setToolsStatus("");
    try {
      const updated = await setAgentToolSelection(
        toolTrigger,
        Array.from(current),
        currentAgentId,
      );
      setToolCatalog(updated);
      setToolsStatus(`Saved ${toolTrigger} tool selection.`);
    } catch (error) {
      setToolsStatus(
        error instanceof Error ? error.message : "Failed to save tool selection.",
      );
    } finally {
      setToolsSaving(false);
    }
  }

  function toggleBulkAgent(agentId: string) {
    setSelectedAgentIds((previous) =>
      previous.includes(agentId)
        ? previous.filter((item) => item !== agentId)
        : [...previous, agentId],
    );
  }

  async function runBulkExport() {
    if (selectedAgentIds.length === 0 || bulkBusy) return;
    setBulkBusy(true);
    setBulkStatus("");
    try {
      const exported = await bulkExportAgents(selectedAgentIds);
      const blob = new Blob([JSON.stringify(exported, null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `agents-export-${Date.now()}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
      setBulkStatus(`Exported ${exported.agents.length} agents.`);
    } catch (error) {
      setBulkStatus(error instanceof Error ? error.message : "Bulk export failed.");
    } finally {
      setBulkBusy(false);
    }
  }

  async function runBulkDelete() {
    if (selectedAgentIds.length === 0 || bulkBusy) return;
    setBulkBusy(true);
    setBulkStatus("");
    try {
      const result = await bulkDeleteAgents(selectedAgentIds);
      setSelectedAgentIds([]);
      setBulkStatus(`Deleted ${result.deleted_count} agent(s).`);
    } catch (error) {
      setBulkStatus(error instanceof Error ? error.message : "Bulk delete failed.");
    } finally {
      setBulkBusy(false);
    }
  }

  function toggleSection(key: SidebarSectionKey) {
    setSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <aside className="panel-shell flex min-h-0 flex-col">
      <div className="ui-panel-header">
        <div>
          <h2 className="ui-panel-title">Agent Console</h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Switch agents, manage bulk actions, and tune tool access without
            leaving the workspace.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral" className="max-w-[180px] truncate">
            Agent: {currentAgentId}
          </Badge>
          <Button
            type="button"
            size="sm"
            className="px-2"
            onClick={() => setSections(DEFAULT_SECTIONS)}
          >
            Expand All
          </Button>
          <Button
            type="button"
            size="sm"
            className="px-2"
            onClick={() =>
              setSections({
                agents: false,
                tools: false,
              })
            }
          >
            Collapse All
          </Button>
        </div>
      </div>

      <div className="ui-scroll-area ui-section-stack flex min-h-0 flex-1 flex-col p-4">
        <section className="ui-section-card panel-shell">
          <div className="ui-section-header">
            <div className="min-w-0">
              <span className="ui-section-title">Agents</span>
              <div className="ui-section-description">
                Create focused agent workspaces and manage the current roster.
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              className="px-2"
              aria-expanded={sections.agents}
              onClick={() => toggleSection("agents")}
            >
              {sections.agents ? "Collapse" : "Expand"}
            </Button>
          </div>
          {sections.agents ? (
            <div className="ui-section-content">
              <label className="ui-label" htmlFor="agent-selector">
                Agent
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
              <div className="mt-4 rounded-[var(--radius-2)] border border-[var(--border)] bg-[var(--surface-inset)] p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="ui-label">Bulk Actions</span>
                  <Badge tone="neutral">{selectedAgentIds.length} selected</Badge>
                </div>
                <ul className="max-h-36 space-y-1 overflow-auto pr-1">
                  {agents.map((agent) => (
                    <li
                      key={`bulk-${agent.agent_id}`}
                      className="flex items-center justify-between rounded border border-transparent px-2 py-1 hover:border-[var(--border)]"
                    >
                      <label className="flex min-w-0 items-center gap-2 text-xs text-[var(--muted)]">
                        <input
                          type="checkbox"
                          checked={selectedAgentIds.includes(agent.agent_id)}
                          onChange={() => toggleBulkAgent(agent.agent_id)}
                        />
                        <span className="ui-mono truncate">{agent.agent_id}</span>
                      </label>
                      <span className="text-xs text-[var(--muted-soft)]">
                        {agent.active_sessions}/{agent.archived_sessions}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex flex-wrap gap-1">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() =>
                      setSelectedAgentIds(agents.map((item) => item.agent_id))
                    }
                  >
                    Select All
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => setSelectedAgentIds([])}
                  >
                    Clear
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    loading={bulkBusy}
                    disabled={selectedAgentIds.length === 0}
                    onClick={() => {
                      void runBulkExport();
                    }}
                  >
                    Export
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    loading={bulkBusy}
                    disabled={selectedAgentIds.length === 0}
                    onClick={() => {
                      void runBulkDelete();
                    }}
                  >
                    Delete
                  </Button>
                </div>
                {bulkStatus ? (
                  <p className="ui-helper mt-2" aria-live="polite">
                    {bulkStatus}
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}
        </section>

        <section className="ui-section-card panel-shell">
          <div className="ui-section-header">
            <div className="min-w-0">
              <span className="ui-section-title">Agent Tools</span>
              <div className="ui-section-description">
                Explicitly allow tools per trigger so chat, cron, and heartbeat
                runs match the agent’s role.
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Badge tone="neutral">{filteredTools.length}</Badge>
              <Button
                type="button"
                size="sm"
                className="px-2"
                aria-expanded={sections.tools}
                onClick={() => toggleSection("tools")}
              >
                {sections.tools ? "Collapse" : "Expand"}
              </Button>
            </div>
          </div>
          {sections.tools ? (
            <div className="ui-section-content">
              <TabsList
                className="grid grid-cols-3"
                ariaLabel="Tool trigger scope"
                value={toolTrigger}
                onChange={(value) => setToolTrigger(value as ToolSelectionTrigger)}
              >
                <TabButton id="tools-tab-chat" controls="tools-panel" value="chat">
                  Chat
                </TabButton>
                <TabButton
                  id="tools-tab-heartbeat"
                  controls="tools-panel"
                  value="heartbeat"
                >
                  Heartbeat
                </TabButton>
                <TabButton id="tools-tab-cron" controls="tools-panel" value="cron">
                  Cron
                </TabButton>
              </TabsList>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <Input
                  value={toolQuery}
                  onChange={(event) => setToolQuery(event.target.value)}
                  placeholder="Search tools..."
                  className="sm:col-span-3"
                  aria-label="Search tools"
                />
                <Select
                  value={toolStatusFilter}
                  onChange={(event) =>
                    setToolStatusFilter(event.target.value as ToolStatusFilter)
                  }
                  aria-label="Filter tools by status"
                >
                  <option value="all">All status</option>
                  <option value="enabled">Enabled</option>
                  <option value="disabled">Disabled</option>
                </Select>
                <Select
                  value={toolCategoryFilter}
                  onChange={(event) => setToolCategoryFilter(event.target.value)}
                  aria-label="Filter tools by category"
                  className="sm:col-span-2"
                >
                  <option value="all">All categories</option>
                  {toolCategories.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </Select>
              </div>
              <div
                id="tools-panel"
                role="tabpanel"
                aria-labelledby={`tools-tab-${toolTrigger}`}
                className="mt-2"
              >
                {toolsLoading ? (
                  <div className="ui-status" aria-live="polite">
                    Loading tools…
                  </div>
                ) : !toolCatalog || toolCatalog.tools.length === 0 ? (
                  <EmptyState
                    title="No Tools"
                    description="No tools are registered for this agent."
                  />
                ) : filteredTools.length === 0 ? (
                  <EmptyState
                    title="No Matching Tools"
                    description="Change search or filters to see tool rows."
                  />
                ) : (
                  <div className="space-y-2 pr-1">
                    {groupedTools.map(([category, tools]) => (
                      <details
                        key={`${toolTrigger}-${category}`}
                        className="rounded border border-[var(--border)] bg-[var(--surface-2)] p-2"
                        open
                      >
                        <summary className="cursor-pointer select-none text-xs font-semibold text-[var(--muted)]">
                          {category} · {tools.length}
                        </summary>
                        <ul className="mt-2 space-y-1">
                          {tools.map((tool) => {
                            const explicit = selectedToolNames.has(tool.name);
                            const triggerState = tool.trigger_status[toolTrigger];
                            return (
                              <li
                                key={`${toolTrigger}-${category}-${tool.name}`}
                                className="rounded border border-transparent px-2 py-1 hover:border-[var(--border)]"
                              >
                                <label className="flex min-h-[44px] cursor-pointer items-start justify-between gap-2 text-xs">
                                  <div className="min-w-0 space-y-1">
                                    <div className="flex items-center gap-1">
                                      <span className="ui-mono truncate text-[var(--text)]">
                                        {tool.name}
                                      </span>
                                      <Badge
                                        tone={triggerState.enabled ? "success" : "warn"}
                                        className="text-[10px]"
                                      >
                                        {triggerState.enabled ? "Enabled" : "Blocked"}
                                      </Badge>
                                    </div>
                                    <div className="line-clamp-2 text-[var(--muted)]">
                                      {tool.description}
                                    </div>
                                    <div className="text-[11px] text-[var(--muted-soft)]">
                                      {triggerState.reason}
                                    </div>
                                  </div>
                                  <input
                                    type="checkbox"
                                    checked={explicit}
                                    disabled={toolsSaving}
                                    onChange={() => {
                                      void toggleToolSelection(tool.name);
                                    }}
                                    aria-label={`Toggle ${tool.name} in ${toolTrigger} explicit allowlist`}
                                  />
                                </label>
                              </li>
                            );
                          })}
                        </ul>
                      </details>
                    ))}
                  </div>
                )}
                <p className="ui-helper mt-2" aria-live="polite">
                  {toolsStatus ||
                    "Tip: use search + category filters, then toggle enabled checkboxes for this trigger."}
                </p>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </aside>
  );
}
