"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { listSkills, listWorkspaceFiles } from "@/lib/api";
import { useAppStore } from "@/lib/store";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[300px] items-center justify-center rounded-lg border border-gray-300 bg-white text-xs text-gray-500">
      Loading editor...
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

export function InspectorPanel() {
  const [skillFileOptions, setSkillFileOptions] = useState<string[]>([]);
  const [workspaceFileOptions, setWorkspaceFileOptions] = useState<string[]>(BASE_FILE_OPTIONS);
  const [workspaceRoot, setWorkspaceRoot] = useState<string>("");

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

  const fileOptions = useMemo(() => {
    const merged = [...workspaceFileOptions, ...skillFileOptions];
    if (!merged.includes(selectedFilePath)) {
      merged.push(selectedFilePath);
    }
    return merged;
  }, [selectedFilePath, skillFileOptions, workspaceFileOptions]);

  return (
    <aside className="panel-shell flex min-h-0 flex-col p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Inspector</h2>
        <button
          className="rounded-lg border border-gray-300 px-2 py-1 text-xs disabled:opacity-60"
          disabled={!fileDirty}
          onClick={() => {
            void saveSelectedFile();
          }}
        >
          Save
        </button>
      </div>

      <div className="mb-2 text-[11px] text-gray-500">
        <div>Agent: {currentAgentId}</div>
        <div className="truncate" title={workspaceRoot || `backend/workspaces/${currentAgentId}`}>
          Root: {`backend/workspaces/${currentAgentId}`}
        </div>
      </div>

      <select
        className="mb-3 rounded-lg border border-gray-300 px-2 py-2 text-xs"
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
      </select>

      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-gray-300">
        <MonacoEditor
          height="100%"
          language="markdown"
          theme="vs"
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
          }}
        />
      </div>
    </aside>
  );
}
