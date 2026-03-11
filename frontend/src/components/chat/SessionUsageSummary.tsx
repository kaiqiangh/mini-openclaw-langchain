"use client";

import { Badge } from "@/components/ui/primitives";
import { ChatToolCall } from "@/lib/store";
import { BadgeTone, debugBadgeTone } from "@/lib/badge-tones";

type UsageMessage = {
  toolCalls: ChatToolCall[];
  selectedSkills: string[];
  skillUses: string[];
};

type UsageSummaryRow = {
  name: string;
  count: number;
};

type SessionUsageSummaryProps = {
  messages: UsageMessage[];
  className?: string;
};

function summarizeSessionUsage(messages: UsageMessage[]): {
  tools: UsageSummaryRow[];
  selectedSkills: UsageSummaryRow[];
  skills: UsageSummaryRow[];
} {
  const toolCounts = new Map<string, number>();
  const selectedSkillCounts = new Map<string, number>();
  const skillCounts = new Map<string, number>();

  for (const message of messages) {
    for (const call of message.toolCalls) {
      const tool = String(call.tool || "").trim();
      if (!tool) continue;
      toolCounts.set(tool, (toolCounts.get(tool) ?? 0) + 1);
    }
    for (const skill of message.selectedSkills) {
      const normalized = String(skill || "").trim();
      if (!normalized) continue;
      selectedSkillCounts.set(
        normalized,
        (selectedSkillCounts.get(normalized) ?? 0) + 1,
      );
    }
    for (const skill of message.skillUses) {
      const normalized = String(skill || "").trim();
      if (!normalized) continue;
      skillCounts.set(normalized, (skillCounts.get(normalized) ?? 0) + 1);
    }
  }

  const sortRows = (rows: Map<string, number>) =>
    [...rows.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => a.name.localeCompare(b.name));

  return {
    tools: sortRows(toolCounts),
    selectedSkills: sortRows(selectedSkillCounts),
    skills: sortRows(skillCounts),
  };
}

function SummaryCard({
  title,
  rows,
  emptyLabel,
  tone,
}: {
  title: string;
  rows: UsageSummaryRow[];
  emptyLabel: string;
  tone: BadgeTone;
}) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="ui-label">{title}</div>
        <Badge tone="neutral">{rows.length}</Badge>
      </div>
      {rows.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {rows.map((row) => (
            <Badge key={row.name} tone={tone} className="ui-mono">
              {row.name} ({row.count})
            </Badge>
          ))}
        </div>
      ) : (
        <div className="mt-2 text-sm text-[var(--muted)]">{emptyLabel}</div>
      )}
    </div>
  );
}

export function SessionUsageSummary({
  messages,
  className = "",
}: SessionUsageSummaryProps) {
  const summary = summarizeSessionUsage(messages);

  return (
    <section className={`grid gap-3 lg:grid-cols-3 ${className}`.trim()}>
      <SummaryCard
        title="Tools Used"
        rows={summary.tools}
        emptyLabel="No tools tracked yet."
        tone={debugBadgeTone("tool")}
      />
      <SummaryCard
        title="Skills Selected"
        rows={summary.selectedSkills}
        emptyLabel="No skills selected yet."
        tone={debugBadgeTone("skill_selected")}
      />
      <SummaryCard
        title="Skills Used"
        rows={summary.skills}
        emptyLabel="No skills used yet."
        tone={debugBadgeTone("skill_used")}
      />
    </section>
  );
}
