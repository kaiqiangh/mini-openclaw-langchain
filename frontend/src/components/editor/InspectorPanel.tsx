"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import {
  getAgentRuntimeDiff,
  getAgentTemplate,
  listAgentTemplates,
  getRuntimeConfig,
  listSkills,
  listWorkspaceFiles,
  setRuntimeConfig,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import {
  Badge,
  Button,
  EmptyState,
  Select,
  Skeleton,
  TabButton,
  TabsList,
} from "@/components/ui/primitives";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[300px] items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-3)] p-4">
      <div className="w-full space-y-2">
        <Skeleton className="h-3 w-1/2" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-5/6" />
      </div>
    </div>
  ),
});

const BASE_FILE_OPTIONS = [
  "memory/MEMORY.md",
  "workspace/AGENTS.md",
  "workspace/SOUL.md",
  "workspace/IDENTITY.md",
  "workspace/USER.md",
  "SKILLS_SNAPSHOT.md",
];

type EditorMode = "file" | "runtime";

export function InspectorPanel() {
  const [skillFileOptions, setSkillFileOptions] = useState<string[]>([]);
  const [workspaceFileOptions, setWorkspaceFileOptions] =
    useState<string[]>(BASE_FILE_OPTIONS);
  const [workspaceRoot, setWorkspaceRoot] = useState<string>("");
  const [editorTheme, setEditorTheme] = useState<"vs" | "vs-dark">("vs");
  const [mode, setMode] = useState<EditorMode>("file");
  const [runtimeConfigContent, setRuntimeConfigContent] =
    useState<string>("{}");
  const [runtimeConfigDirty, setRuntimeConfigDirty] = useState<boolean>(false);
  const [runtimeConfigError, setRuntimeConfigError] = useState<string>("");
  const [runtimeConfigLoading, setRuntimeConfigLoading] =
    useState<boolean>(false);
  const [templates, setTemplates] = useState<
    Array<{ name: string; description: string; path: string; updated_at: number }>
  >([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [diffBaseline, setDiffBaseline] = useState<string>("default");
  const [runtimeDiff, setRuntimeDiff] = useState<{
    summary: { added: number; removed: number; changed: number; total: number };
    added: Record<string, unknown>;
    removed: Record<string, unknown>;
    changed: Record<string, { from: unknown; to: unknown }>;
  } | null>(null);
  const [runtimeDiffLoading, setRuntimeDiffLoading] = useState<boolean>(false);
  const [runtimeDiffError, setRuntimeDiffError] = useState<string>("");
  const [bulkAgentIds, setBulkAgentIds] = useState<string>("default");
  const [bulkPatchMode, setBulkPatchMode] = useState<"merge" | "replace">(
    "merge",
  );
  const [bulkPatchStatus, setBulkPatchStatus] = useState<string>("");
  const [bulkPatchLoading, setBulkPatchLoading] = useState<boolean>(false);

  const {
    agents,
    currentAgentId,
    bulkPatchRuntime,
    selectedFilePath,
    selectedFileContent,
    fileDirty,
    setSelectedFilePath,
    updateSelectedFileContent,
    saveSelectedFile,
  } = useAppStore();

  useEffect(() => {
    let cancelled = false;

    async function loadSkillFiles() {
      try {
        const skills = await listSkills();
        if (cancelled) return;

        const next = skills
          .map((item) => item.location.replace(/^\.\/backend\//, ""))
          .filter(
            (path) => path.startsWith("skills/") && path.endsWith("/SKILL.md"),
          );

        setSkillFileOptions(
          Array.from(new Set(next)).sort((a, b) => a.localeCompare(b)),
        );
      } catch {
        if (!cancelled) {
          setSkillFileOptions([]);
        }
      }
    }

    void loadSkillFiles();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadWorkspaceFiles() {
      try {
        const payload = await listWorkspaceFiles(currentAgentId);
        if (cancelled) return;
        setWorkspaceRoot(payload.workspace_root || "");
        const merged =
          payload.files.length > 0 ? payload.files : BASE_FILE_OPTIONS;
        setWorkspaceFileOptions(
          Array.from(new Set(merged)).sort((a, b) => a.localeCompare(b)),
        );
      } catch {
        if (!cancelled) {
          setWorkspaceRoot("");
          setWorkspaceFileOptions(BASE_FILE_OPTIONS);
        }
      }
    }

    void loadWorkspaceFiles();
    return () => {
      cancelled = true;
    };
  }, [currentAgentId]);

  useEffect(() => {
    let cancelled = false;

    async function loadRuntime() {
      setRuntimeConfigLoading(true);
      setRuntimeConfigError("");
      try {
        const payload = await getRuntimeConfig(currentAgentId);
        if (cancelled) return;
        setRuntimeConfigContent(JSON.stringify(payload, null, 2));
        setRuntimeConfigDirty(false);
      } catch (err) {
        if (cancelled) return;
        setRuntimeConfigError(
          err instanceof Error ? err.message : "Failed to load runtime config",
        );
      } finally {
        if (!cancelled) setRuntimeConfigLoading(false);
      }
    }

    void loadRuntime();
    return () => {
      cancelled = true;
    };
  }, [currentAgentId]);

  useEffect(() => {
    let cancelled = false;

    async function loadTemplates() {
      try {
        const rows = await listAgentTemplates();
        if (cancelled) return;
        setTemplates(rows);
      } catch {
        if (!cancelled) setTemplates([]);
      }
    }

    void loadTemplates();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setBulkAgentIds(currentAgentId);
  }, [currentAgentId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      setEditorTheme(query.matches ? "vs-dark" : "vs");
    };

    applyTheme();
    query.addEventListener("change", applyTheme);
    return () => {
      query.removeEventListener("change", applyTheme);
    };
  }, []);

  const fileOptions = useMemo(() => {
    const merged = [...workspaceFileOptions, ...skillFileOptions];
    if (!merged.includes(selectedFilePath)) {
      merged.push(selectedFilePath);
    }
    return merged;
  }, [selectedFilePath, skillFileOptions, workspaceFileOptions]);

  async function saveRuntimeConfigContent() {
    setRuntimeConfigError("");
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(runtimeConfigContent) as Record<string, unknown>;
    } catch {
      setRuntimeConfigError("Runtime config JSON is invalid.");
      return;
    }
    try {
      const saved = await setRuntimeConfig(payload, currentAgentId);
      setRuntimeConfigContent(JSON.stringify(saved, null, 2));
      setRuntimeConfigDirty(false);
    } catch (err) {
      setRuntimeConfigError(
        err instanceof Error ? err.message : "Failed to save runtime config",
      );
    }
  }

  async function applyTemplateSelection() {
    if (!selectedTemplate) return;
    setRuntimeConfigError("");
    try {
      const template = await getAgentTemplate(selectedTemplate);
      setRuntimeConfigContent(JSON.stringify(template.runtime_config, null, 2));
      setRuntimeConfigDirty(true);
    } catch (err) {
      setRuntimeConfigError(
        err instanceof Error ? err.message : "Failed to load template",
      );
    }
  }

  async function refreshRuntimeDiff() {
    setRuntimeDiffError("");
    setRuntimeDiffLoading(true);
    try {
      const payload = await getAgentRuntimeDiff(currentAgentId, diffBaseline);
      setRuntimeDiff({
        summary: payload.summary,
        added: payload.added,
        removed: payload.removed,
        changed: payload.changed,
      });
    } catch (err) {
      setRuntimeDiff(null);
      setRuntimeDiffError(
        err instanceof Error ? err.message : "Failed to load runtime diff",
      );
    } finally {
      setRuntimeDiffLoading(false);
    }
  }

  async function applyBulkPatch() {
    setBulkPatchStatus("");
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(runtimeConfigContent) as Record<string, unknown>;
    } catch {
      setBulkPatchStatus("Runtime config JSON is invalid.");
      return;
    }

    const targetIds = Array.from(
      new Set(
        bulkAgentIds
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    );
    if (targetIds.length === 0) {
      setBulkPatchStatus("Provide one or more target agent IDs.");
      return;
    }

    setBulkPatchLoading(true);
    try {
      const result = await bulkPatchRuntime(targetIds, payload, bulkPatchMode);
      setBulkPatchStatus(
        `Updated ${result.updated_count}/${result.requested_count} agents.`,
      );
    } catch (err) {
      setBulkPatchStatus(
        err instanceof Error ? err.message : "Bulk patch failed.",
      );
    } finally {
      setBulkPatchLoading(false);
    }
  }

  return (
    <aside className="panel-shell flex min-h-0 flex-col">
      <div className="ui-panel-header">
        <h2 className="ui-panel-title">Inspector</h2>
        <Button
          type="button"
          size="sm"
          className="px-3"
          disabled={mode === "file" ? !fileDirty : !runtimeConfigDirty}
          onClick={() => {
            if (mode === "file") {
              void saveSelectedFile();
            } else {
              void saveRuntimeConfigContent();
            }
          }}
        >
          Save
        </Button>
      </div>

      <TabsList
        className="mx-4 mt-3 grid-cols-2"
        ariaLabel="Inspector mode"
        value={mode}
        onChange={(value) => setMode(value as EditorMode)}
      >
        <TabButton
          id="inspector-tab-file"
          controls="inspector-panel-file"
          value="file"
        >
          Files
        </TabButton>
        <TabButton
          id="inspector-tab-runtime"
          controls="inspector-panel-runtime"
          value="runtime"
        >
          Runtime Config
        </TabButton>
      </TabsList>

      <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge tone="neutral">Agent {currentAgentId}</Badge>
          {mode === "file" ? (
            <Badge tone="accent">Workspace</Badge>
          ) : (
            <Badge tone="warn">Runtime</Badge>
          )}
          <span
            className="ui-helper ui-mono min-w-0 truncate"
            title={workspaceRoot || `backend/workspaces/${currentAgentId}`}
          >
            {`backend/workspaces/${currentAgentId}`}
          </span>
        </div>

        {mode === "file" && fileOptions.length === 0 ? (
          <EmptyState
            title="No Files"
            description="No workspace or skill files were found."
          />
        ) : mode === "file" ? (
          <div
            id="inspector-panel-file"
            role="tabpanel"
            aria-labelledby="inspector-tab-file"
            className="flex min-h-0 flex-1 flex-col gap-3"
          >
            <label className="ui-label" htmlFor="inspector-file-select">
              File
            </label>
            <Select
              id="inspector-file-select"
              name="inspector-file-select"
              className="ui-mono text-xs"
              value={selectedFilePath}
              onChange={(event) => {
                void setSelectedFilePath(event.target.value);
              }}
            >
              {fileOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </Select>

            <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-3)]">
              <MonacoEditor
                height="100%"
                language="markdown"
                theme={editorTheme}
                value={selectedFileContent}
                onChange={(value) => updateSelectedFileContent(value ?? "")}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: "on",
                  wordWrap: "on",
                  smoothScrolling: true,
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  fontFamily: "var(--font-mono)",
                }}
              />
            </div>
          </div>
        ) : (
          <div
            id="inspector-panel-runtime"
            role="tabpanel"
            aria-labelledby="inspector-tab-runtime"
            className="flex min-h-0 flex-1 flex-col gap-3"
          >
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-2 text-sm text-[var(--muted)]">
              Edit validated runtime settings for this agent. Save will call
              `/api/v1/agents/&lt;agent_id&gt;/config/runtime`.
            </div>
            <div className="grid gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 md:grid-cols-2">
              <label className="block">
                <span className="ui-label">Template</span>
                <Select
                  className="mt-1 ui-mono text-xs"
                  value={selectedTemplate}
                  onChange={(event) => setSelectedTemplate(event.target.value)}
                >
                  <option value="">Select template…</option>
                  {templates.map((template) => (
                    <option key={template.name} value={template.name}>
                      {template.name}
                    </option>
                  ))}
                </Select>
              </label>
              <div className="flex items-end">
                <Button
                  type="button"
                  size="sm"
                  className="w-full"
                  disabled={!selectedTemplate}
                  onClick={() => {
                    void applyTemplateSelection();
                  }}
                >
                  Load Template Into Editor
                </Button>
              </div>
              <label className="block">
                <span className="ui-label">Diff Baseline</span>
                <Select
                  className="mt-1 ui-mono text-xs"
                  value={diffBaseline}
                  onChange={(event) => setDiffBaseline(event.target.value)}
                >
                  <option value="default">default</option>
                  {agents.map((agent) => (
                    <option
                      key={`baseline-agent-${agent.agent_id}`}
                      value={`agent:${agent.agent_id}`}
                    >
                      agent:{agent.agent_id}
                    </option>
                  ))}
                  {templates.map((template) => (
                    <option
                      key={`baseline-template-${template.name}`}
                      value={`template:${template.name}`}
                    >
                      template:{template.name}
                    </option>
                  ))}
                </Select>
              </label>
              <div className="flex items-end">
                <Button
                  type="button"
                  size="sm"
                  loading={runtimeDiffLoading}
                  className="w-full"
                  onClick={() => {
                    void refreshRuntimeDiff();
                  }}
                >
                  Compare Runtime
                </Button>
              </div>
              <label className="block md:col-span-2">
                <span className="ui-label">Bulk Patch Target Agent IDs</span>
                <input
                  className="ui-input mt-1 ui-mono text-xs"
                  value={bulkAgentIds}
                  onChange={(event) => setBulkAgentIds(event.target.value)}
                  placeholder="default, elon"
                />
                <span className="ui-helper mt-1 block">
                  Comma-separated list of agents to patch using current editor JSON.
                </span>
              </label>
              <label className="block">
                <span className="ui-label">Bulk Patch Mode</span>
                <Select
                  className="mt-1 ui-mono text-xs"
                  value={bulkPatchMode}
                  onChange={(event) =>
                    setBulkPatchMode(event.target.value as "merge" | "replace")
                  }
                >
                  <option value="merge">merge</option>
                  <option value="replace">replace</option>
                </Select>
              </label>
              <div className="flex items-end">
                <Button
                  type="button"
                  size="sm"
                  loading={bulkPatchLoading}
                  className="w-full"
                  onClick={() => {
                    void applyBulkPatch();
                  }}
                >
                  Apply Bulk Patch
                </Button>
              </div>
            </div>
            {runtimeConfigError ? (
              <div className="ui-alert" role="alert">
                {runtimeConfigError}
              </div>
            ) : null}
            {runtimeDiffError ? (
              <div className="ui-alert" role="alert">
                {runtimeDiffError}
              </div>
            ) : null}
            {bulkPatchStatus ? (
              <div className="ui-status" aria-live="polite">
                {bulkPatchStatus}
              </div>
            ) : null}
            <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-3)]">
              <MonacoEditor
                height="100%"
                language="json"
                theme={editorTheme}
                value={runtimeConfigContent}
                onChange={(value) => {
                  setRuntimeConfigContent(value ?? "");
                  setRuntimeConfigDirty(true);
                }}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: "on",
                  wordWrap: "on",
                  smoothScrolling: true,
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  readOnly: runtimeConfigLoading,
                  fontFamily: "var(--font-mono)",
                }}
              />
            </div>
            {runtimeDiff ? (
              <div className="max-h-56 overflow-auto rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-xs">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">Added {runtimeDiff.summary.added}</Badge>
                  <Badge tone="warn">Removed {runtimeDiff.summary.removed}</Badge>
                  <Badge tone="accent">Changed {runtimeDiff.summary.changed}</Badge>
                  <Badge tone="success">Total {runtimeDiff.summary.total}</Badge>
                </div>
                <div className="space-y-2">
                  {Object.entries(runtimeDiff.changed)
                    .slice(0, 60)
                    .map(([path, value]) => (
                      <div key={`changed-${path}`} className="rounded border border-[var(--border)] p-2">
                        <div className="ui-mono text-[var(--text)]">{path}</div>
                        <div className="text-[var(--muted)]">
                          {JSON.stringify(value.from)} → {JSON.stringify(value.to)}
                        </div>
                      </div>
                    ))}
                  {Object.entries(runtimeDiff.added)
                    .slice(0, 40)
                    .map(([path, value]) => (
                      <div key={`added-${path}`} className="rounded border border-[var(--border)] p-2">
                        <div className="ui-mono text-[var(--success)]">+ {path}</div>
                        <div className="text-[var(--muted)]">
                          {JSON.stringify(value)}
                        </div>
                      </div>
                    ))}
                  {Object.entries(runtimeDiff.removed)
                    .slice(0, 40)
                    .map(([path, value]) => (
                      <div key={`removed-${path}`} className="rounded border border-[var(--border)] p-2">
                        <div className="ui-mono text-[var(--danger)]">- {path}</div>
                        <div className="text-[var(--muted)]">
                          {JSON.stringify(value)}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </aside>
  );
}
