"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSetupStatus, configureSystem } from "@/lib/api";

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

export default function SetupPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [adminToken, setAdminToken] = useState("");
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [configuring, setConfiguring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSetupStatus()
      .then((status) => {
        if (!status.needs_setup) {
          router.replace("/");
        }
      })
      .catch(() => {});
  }, [router]);

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
