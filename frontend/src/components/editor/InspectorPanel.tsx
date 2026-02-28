"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { getRuntimeConfig, listSkills, listWorkspaceFiles, setRuntimeConfig } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Badge, Button, EmptyState, Select, Skeleton, TabButton, TabsList } from "@/components/ui/primitives";

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
  const [workspaceFileOptions, setWorkspaceFileOptions] = useState<string[]>(BASE_FILE_OPTIONS);
  const [workspaceRoot, setWorkspaceRoot] = useState<string>("");
  const [editorTheme, setEditorTheme] = useState<"vs" | "vs-dark">("vs");
  const [mode, setMode] = useState<EditorMode>("file");
  const [runtimeConfigContent, setRuntimeConfigContent] = useState<string>("{}");
  const [runtimeConfigDirty, setRuntimeConfigDirty] = useState<boolean>(false);
  const [runtimeConfigError, setRuntimeConfigError] = useState<string>("");
  const [runtimeConfigLoading, setRuntimeConfigLoading] = useState<boolean>(false);

  const {
    currentAgentId,
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
          .filter((path) => path.startsWith("skills/") && path.endsWith("/SKILL.md"));

        setSkillFileOptions(Array.from(new Set(next)).sort((a, b) => a.localeCompare(b)));
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
        const merged = payload.files.length > 0 ? payload.files : BASE_FILE_OPTIONS;
        setWorkspaceFileOptions(Array.from(new Set(merged)).sort((a, b) => a.localeCompare(b)));
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
        setRuntimeConfigError(err instanceof Error ? err.message : "Failed to load runtime config");
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
      setRuntimeConfigError(err instanceof Error ? err.message : "Failed to save runtime config");
    }
  }

  return (
    <aside className="panel-shell flex min-h-0 flex-col">
      <div className="ui-panel-header">
        <h2 className="ui-panel-title">Inspector</h2>
        <Button
          type="button"
          className="px-3 text-[11px]"
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

      <TabsList className="mx-4 mt-3 grid-cols-2">
        <TabButton type="button" active={mode === "file"} onClick={() => setMode("file")}>
          Files
        </TabButton>
        <TabButton type="button" active={mode === "runtime"} onClick={() => setMode("runtime")}>
          Runtime Config
        </TabButton>
      </TabsList>

      <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <div className="flex flex-wrap gap-2 text-[11px]">
          <Badge tone="neutral">Agent {currentAgentId}</Badge>
          {mode === "file" ? <Badge tone="accent">Workspace</Badge> : <Badge tone="warn">Runtime</Badge>}
          <span
            className="ui-helper ui-mono min-w-0 truncate"
            title={workspaceRoot || `backend/workspaces/${currentAgentId}`}
          >
            {`backend/workspaces/${currentAgentId}`}
          </span>
        </div>

        {mode === "file" && fileOptions.length === 0 ? (
          <EmptyState title="No Files" description="No workspace or skill files were found." />
        ) : mode === "file" ? (
          <>
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
          </>
        ) : (
          <>
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-2 text-xs text-[var(--muted)]">
              Edit validated runtime settings for this agent. Save will call `/api/config/runtime`.
            </div>
            {runtimeConfigError ? (
              <div className="rounded-md border border-[var(--danger)] bg-[var(--danger-soft)] px-3 py-2 text-xs text-[var(--danger)]">
                {runtimeConfigError}
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
          </>
        )}
      </div>
    </aside>
  );
}
