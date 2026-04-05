"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { DelegateBadge } from "@/components/delegates/DelegateBadge";
import { DelegateResultCard } from "@/components/delegates/DelegateResultCard";
import {
  Badge,
  Button,
  EmptyState,
  Panel,
  PanelHeader,
  PanelTitle,
  Skeleton,
} from "@/components/ui/primitives";
import {
  getDelegateDetail,
  listDelegates,
  type DelegateDetail,
  type DelegateSummary,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

function formatTimestamp(value: number | null | undefined) {
  if (!value) return "Unknown time";
  return new Date(value).toLocaleString();
}

function DelegatesPageContent() {
  const searchParams = useSearchParams();
  const {
    currentAgentId,
    currentSessionId,
    delegates: liveDelegates,
  } = useAppStore();

  const queryAgentId = searchParams.get("agent")?.trim() || "";
  const querySessionId = searchParams.get("session")?.trim() || "";
  const agentId = queryAgentId || currentAgentId || "default";
  const sessionId = querySessionId || currentSessionId || "";

  const [fetchedDelegates, setFetchedDelegates] = useState<DelegateSummary[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [selectedDelegateId, setSelectedDelegateId] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [delegateDetail, setDelegateDetail] = useState<DelegateDetail | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const isActiveSession =
    Boolean(sessionId) &&
    agentId === currentAgentId &&
    sessionId === currentSessionId;

  const visibleDelegates = useMemo(() => {
    if (isActiveSession && liveDelegates.length > 0) {
      return liveDelegates;
    }
    return fetchedDelegates;
  }, [fetchedDelegates, isActiveSession, liveDelegates]);

  useEffect(() => {
    if (!sessionId) {
      setFetchedDelegates([]);
      setListError("");
      setListLoading(false);
      return;
    }

    let cancelled = false;
    async function loadDelegates() {
      setListLoading(true);
      setListError("");
      try {
        const response = await listDelegates(agentId, sessionId);
        if (cancelled) return;
        setFetchedDelegates(response.delegates);
      } catch (error) {
        if (cancelled) return;
        setFetchedDelegates([]);
        setListError(
          error instanceof Error ? error.message : "Failed to load delegates",
        );
      } finally {
        if (!cancelled) {
          setListLoading(false);
        }
      }
    }

    void loadDelegates();
    return () => {
      cancelled = true;
    };
  }, [agentId, refreshNonce, sessionId]);

  useEffect(() => {
    if (visibleDelegates.length === 0) {
      setSelectedDelegateId(null);
      return;
    }
    if (
      selectedDelegateId &&
      visibleDelegates.some((delegate) => delegate.delegate_id === selectedDelegateId)
    ) {
      return;
    }
    setSelectedDelegateId(visibleDelegates[0]?.delegate_id ?? null);
  }, [selectedDelegateId, visibleDelegates]);

  useEffect(() => {
    if (!sessionId || !selectedDelegateId) {
      setDelegateDetail(null);
      setDetailError("");
      setDetailLoading(false);
      return;
    }

    const delegateId = selectedDelegateId;

    let cancelled = false;
    async function loadDetail() {
      setDetailLoading(true);
      setDetailError("");
      try {
        const detail = await getDelegateDetail(agentId, sessionId, delegateId);
        if (cancelled) return;
        setDelegateDetail(detail);
      } catch (error) {
        if (cancelled) return;
        setDelegateDetail(null);
        setDetailError(
          error instanceof Error ? error.message : "Failed to load delegate detail",
        );
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [agentId, selectedDelegateId, sessionId]);

  if (!sessionId) {
    return (
      <main className="app-main flex min-h-0 flex-1 flex-col overflow-hidden p-3 sm:p-4">
        <Panel className="min-h-[240px]">
          <PanelHeader>
            <PanelTitle>Delegates</PanelTitle>
          </PanelHeader>
          <EmptyState
            title="No session selected"
            description="Select a session or open this page with agent and session query parameters to inspect delegate activity."
          />
        </Panel>
      </main>
    );
  }

  return (
    <main className="app-main flex min-h-0 flex-1 flex-col overflow-hidden p-3 sm:p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold text-[var(--text)]">Delegates</h1>
        <Badge tone="neutral">Agent {agentId}</Badge>
        <Badge tone="neutral">Session {sessionId}</Badge>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={() => setRefreshNonce((value) => value + 1)}
        >
          Refresh
        </Button>
      </div>

      {listError ? (
        <div className="mb-3 rounded border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
          {listError}
        </div>
      ) : null}

      <section className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[320px,minmax(0,1fr)]">
        <Panel className="min-h-[320px] overflow-hidden">
          <PanelHeader>
            <PanelTitle>Delegate List</PanelTitle>
            <Badge tone="neutral">{visibleDelegates.length}</Badge>
          </PanelHeader>
          <div className="ui-scroll-area max-h-[calc(100vh-240px)] p-2">
            {listLoading && visibleDelegates.length === 0 ? (
              <div className="space-y-2">
                <Skeleton className="h-20 rounded-xl" />
                <Skeleton className="h-20 rounded-xl" />
              </div>
            ) : visibleDelegates.length === 0 ? (
              <EmptyState
                title="No delegates yet"
                description="This session has no delegate activity yet."
              />
            ) : (
              <div className="space-y-2">
                {visibleDelegates.map((delegate) => {
                  const selected = delegate.delegate_id === selectedDelegateId;
                  return (
                    <button
                      key={delegate.delegate_id}
                      type="button"
                      onClick={() => setSelectedDelegateId(delegate.delegate_id)}
                      className={`w-full rounded-xl border p-3 text-left transition ${
                        selected
                          ? "border-[var(--accent)] bg-[var(--surface-2)]"
                          : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--accent)]/50"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium text-[var(--text)]">
                            {delegate.task}
                          </div>
                          <div className="mt-1 text-xs text-[var(--muted)]">
                            {formatTimestamp(delegate.created_at)}
                          </div>
                        </div>
                        <DelegateBadge status={delegate.status} role={delegate.role} />
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Panel>

        <Panel className="min-h-[320px] overflow-hidden">
          <PanelHeader>
            <PanelTitle>Delegate Detail</PanelTitle>
            {delegateDetail ? (
              <DelegateBadge
                status={delegateDetail.status}
                role={delegateDetail.role}
              />
            ) : null}
          </PanelHeader>
          <div className="ui-scroll-area max-h-[calc(100vh-240px)] p-4">
            {detailLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-6 w-40 rounded-full" />
                <Skeleton className="h-24 rounded-xl" />
                <Skeleton className="h-24 rounded-xl" />
              </div>
            ) : detailError ? (
              <div className="rounded border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
                {detailError}
              </div>
            ) : delegateDetail ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  <h2 className="text-base font-semibold text-[var(--text)]">
                    {delegateDetail.task}
                  </h2>
                  <div className="flex flex-wrap gap-2 text-xs text-[var(--muted)]">
                    <span>Delegate {delegateDetail.delegate_id}</span>
                    <span>Sub-session {delegateDetail.sub_session_id}</span>
                    <span>{formatTimestamp(delegateDetail.created_at)}</span>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {delegateDetail.allowed_tools.map((toolName) => (
                    <Badge key={toolName} tone="neutral">
                      {toolName}
                    </Badge>
                  ))}
                </div>

                <DelegateResultCard delegate={delegateDetail} />
              </div>
            ) : (
              <EmptyState
                title="Select a delegate"
                description="Choose a delegate from the list to inspect its task, status, and result."
              />
            )}
          </div>
        </Panel>
      </section>
    </main>
  );
}

export default function DelegatesPage() {
  return (
    <Suspense
      fallback={
        <main className="app-main flex min-h-0 flex-1 flex-col overflow-hidden p-3 sm:p-4">
          <Panel className="min-h-[240px]">
            <PanelHeader>
              <PanelTitle>Delegates</PanelTitle>
            </PanelHeader>
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-40 rounded-full" />
              <Skeleton className="h-24 rounded-xl" />
              <Skeleton className="h-24 rounded-xl" />
            </div>
          </Panel>
        </main>
      }
    >
      <DelegatesPageContent />
    </Suspense>
  );
}
