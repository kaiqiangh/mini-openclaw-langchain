"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

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
type RuntimeSectionKey = "controls" | "editor" | "diff";

const INSPECTOR_EXPANDED_KEY = "mini-openclaw:inspector-expanded:v1";
const RUNTIME_SECTION_KEY = "mini-openclaw:inspector-runtime-sections:v1";
const DEFAULT_RUNTIME_SECTIONS: Record<RuntimeSectionKey, boolean> = {
  controls: true,
  editor: true,
  diff: true,
};

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
  const [runtimeActionStatus, setRuntimeActionStatus] = useState<string>("");
  const [runtimeFullscreen, setRuntimeFullscreen] = useState<boolean>(false);
  const [inspectorExpanded, setInspectorExpanded] = useState<boolean>(true);
  const [runtimeSections, setRuntimeSections] =
    useState<Record<RuntimeSectionKey, boolean>>(DEFAULT_RUNTIME_SECTIONS);
  const runtimeEditorRef = useRef<any>(null);
  const fileEditorRef = useRef<any>(null);

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

  useEffect(() => {
    if (typeof window === "undefined") return;
    const expandedRaw = window.localStorage.getItem(INSPECTOR_EXPANDED_KEY);
    if (expandedRaw === "0") {
      setInspectorExpanded(false);
    }
    try {
      const raw = window.localStorage.getItem(RUNTIME_SECTION_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<Record<RuntimeSectionKey, boolean>>;
      setRuntimeSections({
        controls: parsed.controls ?? true,
        editor: parsed.editor ?? true,
        diff: parsed.diff ?? true,
      });
    } catch {
      setRuntimeSections(DEFAULT_RUNTIME_SECTIONS);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      INSPECTOR_EXPANDED_KEY,
      inspectorExpanded ? "1" : "0",
    );
  }, [inspectorExpanded]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(RUNTIME_SECTION_KEY, JSON.stringify(runtimeSections));
  }, [runtimeSections]);

  useEffect(() => {
    setRuntimeActionStatus("");
  }, [currentAgentId, mode]);

  useEffect(() => {
    if (mode !== "runtime" && runtimeFullscreen) {
      setRuntimeFullscreen(false);
    }
  }, [mode, runtimeFullscreen]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (mode !== "runtime") return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveRuntimeConfigContent();
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
        event.preventDefault();
        void runtimeEditorRef.current?.getAction?.("actions.find")?.run?.();
        return;
      }
      if (event.key === "Escape" && runtimeFullscreen) {
        event.preventDefault();
        setRuntimeFullscreen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [mode, runtimeFullscreen]);

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

  function formatRuntimeJson() {
    try {
      const parsed = JSON.parse(runtimeConfigContent) as Record<string, unknown>;
      setRuntimeConfigContent(JSON.stringify(parsed, null, 2));
      setRuntimeConfigDirty(true);
      setRuntimeActionStatus("JSON formatted.");
      setRuntimeConfigError("");
    } catch {
      setRuntimeConfigError("Runtime config JSON is invalid.");
      setRuntimeActionStatus("");
    }
  }

  function validateRuntimeJson() {
    try {
      JSON.parse(runtimeConfigContent);
      setRuntimeConfigError("");
      setRuntimeActionStatus("JSON is valid.");
    } catch {
      setRuntimeConfigError("Runtime config JSON is invalid.");
      setRuntimeActionStatus("");
    }
  }

  async function copyRuntimeJson() {
    try {
      await navigator.clipboard.writeText(runtimeConfigContent);
      setRuntimeActionStatus("Runtime config copied.");
    } catch {
      setRuntimeActionStatus("Copy failed.");
    }
  }

  function openRuntimeSearch() {
    void runtimeEditorRef.current?.getAction?.("actions.find")?.run?.();
  }

  function toggleRuntimeSection(key: RuntimeSectionKey) {
    setRuntimeSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <aside
      className={`panel-shell flex min-h-0 flex-col ${runtimeFullscreen ? "fixed inset-3 z-40 shadow-2xl" : ""}`}
    >
      <div className="ui-panel-header">
        <h2 className="ui-panel-title">Inspector</h2>
        <div className="flex items-center gap-2">
          {mode === "runtime" ? (
            <Badge tone={runtimeConfigDirty ? "warn" : "success"}>
              {runtimeConfigDirty ? "Unsaved" : "Saved"}
            </Badge>
          ) : null}
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
          {mode === "runtime" ? (
            <Button
              type="button"
              size="sm"
              className="px-3"
              onClick={() => setRuntimeFullscreen((prev) => !prev)}
            >
              {runtimeFullscreen ? "Exit Focus" : "Focus"}
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            className="px-3"
            aria-expanded={inspectorExpanded}
            onClick={() => setInspectorExpanded((prev) => !prev)}
          >
            {inspectorExpanded ? "Collapse" : "Expand"}
          </Button>
        </div>
      </div>
      {inspectorExpanded ? (
        <>
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

          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
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
                    onMount={(editor) => {
                      fileEditorRef.current = editor;
                    }}
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
                className="flex min-w-0 flex-col gap-3 pb-2"
              >
                <div className="sticky top-0 z-10 flex flex-wrap items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2">
                  <Button type="button" size="sm" onClick={formatRuntimeJson}>
                    Format
                  </Button>
                  <Button type="button" size="sm" onClick={validateRuntimeJson}>
                    Validate
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => void copyRuntimeJson()}
                  >
                    Copy
                  </Button>
                  <Button type="button" size="sm" onClick={openRuntimeSearch}>
                    Search
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    loading={runtimeDiffLoading}
                    onClick={() => {
                      void refreshRuntimeDiff();
                    }}
                  >
                    Diff
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="primary"
                    disabled={!runtimeConfigDirty}
                    onClick={() => {
                      void saveRuntimeConfigContent();
                    }}
                  >
                    Save Runtime
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    className="ml-auto"
                    onClick={() => setRuntimeSections(DEFAULT_RUNTIME_SECTIONS)}
                  >
                    Expand All
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() =>
                      setRuntimeSections({
                        controls: false,
                        editor: false,
                        diff: false,
                      })
                    }
                  >
                    Collapse All
                  </Button>
                </div>

                <section className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="ui-label">Runtime Controls</span>
                    <Button
                      type="button"
                      size="sm"
                      className="px-2"
                      aria-expanded={runtimeSections.controls}
                      onClick={() => toggleRuntimeSection("controls")}
                    >
                      {runtimeSections.controls ? "Collapse" : "Expand"}
                    </Button>
                  </div>
                  {runtimeSections.controls ? (
                    <div className="grid gap-2 md:grid-cols-2">
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
                  ) : null}
                </section>

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
                {runtimeActionStatus ? (
                  <div className="ui-status" aria-live="polite">
                    {runtimeActionStatus}
                  </div>
                ) : null}

                <section className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="ui-label">Runtime Config JSON</span>
                    <Button
                      type="button"
                      size="sm"
                      className="px-2"
                      aria-expanded={runtimeSections.editor}
                      onClick={() => toggleRuntimeSection("editor")}
                    >
                      {runtimeSections.editor ? "Collapse" : "Expand"}
                    </Button>
                  </div>
                  {runtimeSections.editor ? (
                    <div className="h-[34vh] min-h-[260px] overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-3)]">
                      <MonacoEditor
                        height="100%"
                        language="json"
                        theme={editorTheme}
                        value={runtimeConfigContent}
                        onMount={(editor) => {
                          runtimeEditorRef.current = editor;
                        }}
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
                  ) : null}
                </section>

                <section className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="ui-label">Runtime Diff</span>
                    <Button
                      type="button"
                      size="sm"
                      className="px-2"
                      aria-expanded={runtimeSections.diff}
                      onClick={() => toggleRuntimeSection("diff")}
                    >
                      {runtimeSections.diff ? "Collapse" : "Expand"}
                    </Button>
                  </div>
                  {runtimeSections.diff ? (
                    runtimeDiff ? (
                      <div className="max-h-64 overflow-auto rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3 text-xs">
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
                              <div
                                key={`changed-${path}`}
                                className="rounded border border-[var(--border)] p-2"
                              >
                                <div className="ui-mono text-[var(--text)]">{path}</div>
                                <div className="text-[var(--muted)]">
                                  {JSON.stringify(value.from)} → {JSON.stringify(value.to)}
                                </div>
                              </div>
                            ))}
                          {Object.entries(runtimeDiff.added)
                            .slice(0, 40)
                            .map(([path, value]) => (
                              <div
                                key={`added-${path}`}
                                className="rounded border border-[var(--border)] p-2"
                              >
                                <div className="ui-mono text-[var(--success)]">+ {path}</div>
                                <div className="text-[var(--muted)]">
                                  {JSON.stringify(value)}
                                </div>
                              </div>
                            ))}
                          {Object.entries(runtimeDiff.removed)
                            .slice(0, 40)
                            .map(([path, value]) => (
                              <div
                                key={`removed-${path}`}
                                className="rounded border border-[var(--border)] p-2"
                              >
                                <div className="ui-mono text-[var(--danger)]">- {path}</div>
                                <div className="text-[var(--muted)]">
                                  {JSON.stringify(value)}
                                </div>
                              </div>
                            ))}
                        </div>
                      </div>
                    ) : (
                      <EmptyState
                        title="No Diff Loaded"
                        description="Run Compare Runtime to view differences."
                      />
                    )
                  ) : null}
                </section>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="px-4 py-3 text-sm text-[var(--muted)]">
          Inspector is collapsed.
        </div>
      )}
    </aside>
  );
}
