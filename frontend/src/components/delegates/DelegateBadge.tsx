import { Badge } from "@/components/ui/primitives";

interface Props {
  status: "running" | "completed" | "failed" | "timeout";
  role: string;
}

const STATUS: Record<string, { tone: "accent" | "success" | "danger" | "warn"; label: string }> = {
  running: { tone: "accent", label: "Running" },
  completed: { tone: "success", label: "Done" },
  failed: { tone: "danger", label: "Failed" },
  timeout: { tone: "warn", label: "Timeout" },
};

export function DelegateBadge({ status, role }: Props) {
  const cfg = STATUS[status] ?? STATUS.running;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-[11px] text-[var(--muted-soft)]">{role}:</span>
      <Badge tone={cfg.tone}>{cfg.label}</Badge>
    </span>
  );
}
