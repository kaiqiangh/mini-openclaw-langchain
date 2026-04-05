"use client";

import { useCallback, useEffect, useState } from "react";
import {
  configureSystem,
  createHook,
  deleteHook,
  getAgents,
  getHookAudit,
  getSetupStatus,
  listHooks,
  testHook,
  type AgentMeta,
  type HookAuditRow,
  type HookConfigRecord,
} from "@/lib/api";

const STEPS = [
  { id: "token", label: "Admin Token" },
  { id: "llm", label: "LLM Provider" },
  { id: "verify", label: "Verify" },
];

type LlmConfig = {
  provider: "deepseek" | "openai";
  api_key: string;
  base_url?: string;
  model?: string;
};

function StepIndicator({
  currentStep,
}: {
  currentStep: number;
}) {
  return (
    <div className="flex items-center gap-2 mb-8">
      {STEPS.map((step, i) => {
        const isActive = i === currentStep;
        const isComplete = i < currentStep;
        return (
          <div key={step.id} className="flex items-center gap-2">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                isComplete
                  ? "bg-green-600 text-white"
                  : isActive
                    ? "bg-zinc-200 text-zinc-900"
                    : "bg-zinc-800 text-zinc-500"
              }`}
            >
              {isComplete ? "✓" : i + 1}
            </div>
            <span
              className={`text-sm ${
                isActive ? "text-zinc-200" : "text-zinc-500"
              }`}
            >
              {step.label}
            </span>
            {i < STEPS.length - 1 && (
              <div
                className={`w-8 h-px ${
                  isComplete ? "bg-green-600" : "bg-zinc-700"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function TokenStep({
  defaultValue,
  onNext,
}: {
  defaultValue: string;
  onNext: (token: string) => void;
}) {
  const [token, setToken] = useState(defaultValue);
  const [error, setError] = useState("");

  const handleSubmit = () => {
    if (token.length < 8) {
      setError("Token must be at least 8 characters");
      return;
    }
    setError("");
    onNext(token);
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium text-zinc-200">Set Admin Token</h3>
      <p className="text-sm text-zinc-400">
        This token protects the admin API. Use a strong, unique value.
      </p>
      <div>
        <label className="block text-sm text-zinc-400 mb-1">Admin Token</label>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
          placeholder="Enter admin token (min 8 chars)"
          minLength={8}
        />
        {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
      </div>
      <button
        onClick={handleSubmit}
        className="px-4 py-2 bg-zinc-200 text-zinc-900 rounded text-sm font-medium hover:bg-zinc-300"
      >
        Next
      </button>
    </div>
  );
}

function LlmStep({
  onNext,
  onBack,
}: {
  onNext: (config: LlmConfig) => void;
  onBack: () => void;
}) {
  const [provider, setProvider] = useState<"deepseek" | "openai">("deepseek");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = () => {
    if (!apiKey.trim()) {
      setError("API key is required");
      return;
    }
    setError("");
    onNext({
      provider,
      api_key: apiKey.trim(),
      base_url: baseUrl.trim() || undefined,
      model: model.trim() || undefined,
    });
  };

  const defaultModels: Record<string, string> = {
    deepseek: "deepseek-chat",
    openai: "gpt-4o-mini",
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium text-zinc-200">Configure LLM Provider</h3>
      <p className="text-sm text-zinc-400">
        Choose an LLM provider and enter your API key.
      </p>

      <div>
        <label className="block text-sm text-zinc-400 mb-1">Provider</label>
        <div className="flex gap-2">
          {(["deepseek", "openai"] as const).map((p) => (
            <button
              key={p}
              onClick={() => {
                setProvider(p);
                setModel("");
              }}
              className={`px-4 py-2 rounded text-sm ${
                provider === p
                  ? "bg-zinc-200 text-zinc-900"
                  : "bg-zinc-800 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm text-zinc-400 mb-1">API Key</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
          placeholder="sk-..."
        />
      </div>

      <div>
        <label className="block text-sm text-zinc-400 mb-1">
          Base URL <span className="text-zinc-600">(optional)</span>
        </label>
        <input
          type="text"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
          placeholder={provider === "deepseek" ? "https://api.deepseek.com" : "https://api.openai.com"}
        />
      </div>

      <div>
        <label className="block text-sm text-zinc-400 mb-1">
          Model <span className="text-zinc-600">(optional, default: {defaultModels[provider]})</span>
        </label>
        <input
          type="text"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
          placeholder={defaultModels[provider]}
        />
      </div>

      {error && <p className="text-red-400 text-xs">{error}</p>}

      <div className="flex gap-2">
        <button
          onClick={onBack}
          className="px-4 py-2 bg-zinc-800 text-zinc-400 rounded text-sm hover:text-zinc-200"
        >
          Back
        </button>
        <button
          onClick={handleSubmit}
          className="px-4 py-2 bg-zinc-200 text-zinc-900 rounded text-sm font-medium hover:bg-zinc-300"
        >
          Next
        </button>
      </div>
    </div>
  );
}

function VerifyStep({
  token,
  provider,
  onRestart,
}: {
  token: string;
  provider: string;
  onRestart: () => void;
}) {
  const [status, setStatus] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  const handleTest = async () => {
    setStatus("testing");
    setMessage("");
    try {
      const resp = await fetch("/api/v1/setup/status");
      const data = await resp.json();
      if (!data.data?.needs_setup) {
        setStatus("success");
        setMessage("Configuration saved successfully!");
      } else {
        setStatus("error");
        setMessage("Configuration incomplete.");
      }
    } catch {
      setStatus("error");
      setMessage("Failed to verify configuration.");
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium text-zinc-200">Verify & Complete</h3>

      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-zinc-400">Admin Token</span>
          <span className="text-zinc-200">{"•".repeat(Math.min(token.length, 12))}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">LLM Provider</span>
          <span className="text-zinc-200">{provider}</span>
        </div>
      </div>

      <button
        onClick={handleTest}
        disabled={status === "testing"}
        className="px-4 py-2 bg-zinc-200 text-zinc-900 rounded text-sm font-medium hover:bg-zinc-300 disabled:opacity-50"
      >
        {status === "testing" ? "Verifying..." : "Verify Configuration"}
      </button>

      {status === "success" && (
        <div className="p-3 bg-green-900/30 border border-green-800 rounded text-green-300 text-sm">
          {message}
        </div>
      )}
      {status === "error" && (
        <div className="p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">
          {message}
        </div>
      )}

      {status === "success" && (
        <a
          href="/"
          className="inline-block px-4 py-2 bg-green-600 text-white rounded text-sm font-medium hover:bg-green-500"
        >
          Go to Console →
        </a>
      )}

      <div>
        <button
          onClick={onRestart}
          className="text-xs text-zinc-500 hover:text-zinc-300 underline"
        >
          Start over
        </button>
      </div>
    </div>
  );
}

function HooksPanel({
  agents,
  selectedAgentId,
  onSelectAgent,
}: {
  agents: AgentMeta[];
  selectedAgentId: string;
  onSelectAgent: (agentId: string) => void;
}) {
  const [hooks, setHooks] = useState<HookConfigRecord[]>([]);
  const [auditRows, setAuditRows] = useState<HookAuditRow[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hookId, setHookId] = useState("");
  const [hookType, setHookType] = useState("pre_tool_use");
  const [handler, setHandler] = useState("hooks/audit.py");
  const [mode, setMode] = useState("sync");
  const [timeoutMs, setTimeoutMs] = useState("10000");

  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [nextHooks, nextAudit] = await Promise.all([
        listHooks(selectedAgentId),
        getHookAudit(selectedAgentId, 10),
      ]);
      setHooks(nextHooks);
      setAuditRows(nextAudit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load hooks");
    } finally {
      setBusy(false);
    }
  }, [selectedAgentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async () => {
    if (!hookId.trim() || !handler.trim()) {
      setError("Hook id and handler are required.");
      return;
    }
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await createHook(selectedAgentId, {
        id: hookId.trim(),
        type: hookType,
        handler: handler.trim(),
        mode,
        timeout_ms: Number(timeoutMs) || 10000,
      });
      setStatus(`Created hook ${hookId.trim()}.`);
      setHookId("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create hook");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (hookIdToDelete: string) => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await deleteHook(selectedAgentId, hookIdToDelete);
      setStatus(`Deleted hook ${hookIdToDelete}.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete hook");
    } finally {
      setBusy(false);
    }
  };

  const handleTest = async (hookIdToTest: string) => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const result = await testHook(selectedAgentId, hookIdToTest);
      setStatus(
        `${result.hook_id}: ${result.allow ? "allowed" : "denied"}${result.reason ? ` (${result.reason})` : ""}`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to test hook");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h3 className="text-lg font-medium text-zinc-200">Hooks Panel</h3>
        <p className="text-sm text-zinc-400">
          Configure lifecycle hooks and inspect recent hook audit activity.
        </p>
      </div>

      <div>
        <label className="block text-sm text-zinc-400 mb-1">Agent</label>
        <select
          value={selectedAgentId}
          onChange={(event) => onSelectAgent(event.target.value)}
          className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
        >
          {agents.map((agent) => (
            <option key={agent.agent_id} value={agent.agent_id}>
              {agent.agent_id}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Hook ID</label>
          <input
            type="text"
            value={hookId}
            onChange={(e) => setHookId(e.target.value)}
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
            placeholder="audit-pre-tool"
          />
        </div>
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Type</label>
          <select
            value={hookType}
            onChange={(e) => setHookType(e.target.value)}
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
          >
            {[
              "pre_run",
              "pre_prompt_submit",
              "pre_tool_use",
              "post_tool_use",
              "pre_compact",
              "stop",
            ].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Handler</label>
          <input
            type="text"
            value={handler}
            onChange={(e) => setHandler(e.target.value)}
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
            placeholder="hooks/audit.py"
          />
        </div>
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Mode</label>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
          >
            <option value="sync">sync</option>
            <option value="async">async</option>
          </select>
        </div>
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Timeout (ms)</label>
          <input
            type="number"
            value={timeoutMs}
            onChange={(e) => setTimeoutMs(e.target.value)}
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-zinc-200 text-sm focus:outline-none focus:border-zinc-500"
            min={1}
          />
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleCreate}
          disabled={busy}
          className="px-4 py-2 bg-zinc-200 text-zinc-900 rounded text-sm font-medium hover:bg-zinc-300 disabled:opacity-50"
        >
          Add Hook
        </button>
        <button
          onClick={() => void refresh()}
          disabled={busy}
          className="px-4 py-2 bg-zinc-800 text-zinc-200 rounded text-sm hover:bg-zinc-700 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>

      {status ? (
        <div className="p-3 bg-green-900/30 border border-green-800 rounded text-green-300 text-sm">
          {status}
        </div>
      ) : null}
      {error ? (
        <div className="p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">
          {error}
        </div>
      ) : null}

      <div className="space-y-3">
        <h4 className="text-sm font-medium text-zinc-300">Configured Hooks</h4>
        {hooks.length === 0 ? (
          <p className="text-sm text-zinc-500">No hooks configured for this agent.</p>
        ) : (
          hooks.map((hook) => (
            <div
              key={hook.id}
              className="rounded border border-zinc-800 bg-zinc-950/80 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-zinc-200">{hook.id}</div>
                  <div className="text-xs text-zinc-500">
                    {hook.type} · {hook.mode} · {hook.handler}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => void handleTest(hook.id)}
                    disabled={busy}
                    className="px-3 py-1.5 bg-zinc-800 text-zinc-200 rounded text-xs hover:bg-zinc-700 disabled:opacity-50"
                  >
                    Test
                  </button>
                  <button
                    onClick={() => void handleDelete(hook.id)}
                    disabled={busy}
                    className="px-3 py-1.5 bg-red-900/50 text-red-200 rounded text-xs hover:bg-red-800/60 disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="space-y-3">
        <h4 className="text-sm font-medium text-zinc-300">Recent Hook Audit</h4>
        {auditRows.length === 0 ? (
          <p className="text-sm text-zinc-500">No hook audit rows yet.</p>
        ) : (
          auditRows.map((row, index) => (
            <div
              key={`${row.event}-${row.timestamp_ms ?? index}`}
              className="rounded border border-zinc-800 bg-zinc-950/80 p-3 text-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-zinc-200">{row.event}</div>
                <div className="text-xs text-zinc-500">
                  {row.timestamp_ms
                    ? new Date(row.timestamp_ms).toLocaleString()
                    : "no timestamp"}
                </div>
              </div>
              <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-500">
                {JSON.stringify(row.details ?? {}, null, 2)}
              </pre>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function SetupPage() {
  const [currentStep, setCurrentStep] = useState(0);
  const [adminToken, setAdminToken] = useState("");
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [configuring, setConfiguring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [setupReady, setSetupReady] = useState(false);
  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [agentsError, setAgentsError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadSetupState() {
      setStatusLoading(true);
      setError(null);
      try {
        const status = await getSetupStatus();
        if (cancelled) return;
        setSetupReady(!status.needs_setup);

        if (status.needs_setup) {
          setAgents([]);
          setSelectedAgentId("");
          setAgentsError("");
          return;
        }

        setAgentsLoading(true);
        setAgentsError("");
        try {
          const nextAgents = await getAgents();
          if (cancelled) return;
          setAgents(nextAgents);
          setSelectedAgentId((previous) => previous || nextAgents[0]?.agent_id || "");
        } catch (err) {
          if (cancelled) return;
          setAgents([]);
          setSelectedAgentId("");
          setAgentsError(
            err instanceof Error ? err.message : "Failed to load agents",
          );
        } finally {
          if (!cancelled) {
            setAgentsLoading(false);
          }
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load setup state");
      } finally {
        if (!cancelled) {
          setStatusLoading(false);
        }
      }
    }

    void loadSetupState();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleTokenNext = useCallback((token: string) => {
    setAdminToken(token);
    setCurrentStep(1);
  }, []);

  const handleLlmNext = useCallback(
    async (config: LlmConfig) => {
      setLlmConfig(config);
      setConfiguring(true);
      setError(null);
      try {
        await configureSystem({
          admin_token: adminToken,
          llm_provider: config.provider,
          llm_api_key: config.api_key,
          llm_base_url: config.base_url,
          llm_model: config.model,
        });
        setCurrentStep(2);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Configuration failed");
      } finally {
        setConfiguring(false);
      }
    },
    [adminToken],
  );

  const handleBack = useCallback(() => {
    setCurrentStep((s) => Math.max(0, s - 1));
  }, []);

  const handleRestart = useCallback(() => {
    setCurrentStep(0);
    setAdminToken("");
    setLlmConfig(null);
    setError(null);
  }, []);

  if (statusLoading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
        <div className="w-full max-w-md rounded-lg border border-zinc-800 bg-zinc-900 p-6 text-sm text-zinc-400">
          Loading setup status...
        </div>
      </div>
    );
  }

  if (setupReady) {
    return (
      <div className="min-h-screen bg-zinc-950 p-4 sm:p-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6">
            <h1 className="text-2xl font-bold text-zinc-100">Setup & Hooks</h1>
            <p className="mt-2 text-sm text-zinc-400">
              Setup is complete. Use this page to manage runtime hooks and inspect recent hook audit activity.
            </p>
          </div>

          {error ? (
            <div className="rounded-lg border border-red-800 bg-red-900/30 p-4 text-sm text-red-300">
              {error}
            </div>
          ) : null}

          {agentsError ? (
            <div className="rounded-lg border border-red-800 bg-red-900/30 p-4 text-sm text-red-300">
              {agentsError}
            </div>
          ) : null}

          {agentsLoading ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6 text-sm text-zinc-400">
              Loading agents...
            </div>
          ) : agents.length === 0 || !selectedAgentId ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6 text-sm text-zinc-400">
              No agents are available yet. Create an agent, then return here to manage its hooks.
            </div>
          ) : (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6">
              <HooksPanel
                agents={agents}
                selectedAgentId={selectedAgentId}
                onSelectAgent={setSelectedAgentId}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-zinc-100">Setup Wizard</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Configure your mini-openclaw instance
          </p>
        </div>

        <StepIndicator currentStep={currentStep} />

        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6">
          {configuring && (
            <div className="text-zinc-400 text-sm">Saving configuration...</div>
          )}

          {error && (
            <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">
              {error}
            </div>
          )}

          {currentStep === 0 && !configuring && (
            <TokenStep defaultValue={adminToken} onNext={handleTokenNext} />
          )}

          {currentStep === 1 && !configuring && (
            <LlmStep onNext={handleLlmNext} onBack={handleBack} />
          )}

          {currentStep === 2 && (
            <VerifyStep
              token={adminToken}
              provider={llmConfig?.provider ?? ""}
              onRestart={handleRestart}
            />
          )}
        </div>
      </div>
    </div>
  );
}
