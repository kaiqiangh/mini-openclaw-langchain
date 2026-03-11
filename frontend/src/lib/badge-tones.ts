"use client";

export type BadgeTone = "neutral" | "accent" | "success" | "warn" | "danger";

export function sessionScopeTone(scope: "active" | "archived"): BadgeTone {
  return scope === "archived" ? "warn" : "success";
}

export function activityTone(label: string): BadgeTone {
  const normalized = label.trim().toLowerCase();
  if (["running", "loading", "streaming", "recorded"].includes(normalized)) {
    return "accent";
  }
  if (
    [
      "active",
      "enabled",
      "healthy",
      "idle",
      "live",
      "loaded",
      "ready",
    ].includes(normalized)
  ) {
    return "success";
  }
  if (
    ["archived", "disabled", "paused", "removed", "skipped"].some((prefix) =>
      normalized.startsWith(prefix),
    )
  ) {
    return "warn";
  }
  if (
    ["danger", "error", "failed", "failure"].some((prefix) =>
      normalized.startsWith(prefix),
    )
  ) {
    return "danger";
  }
  return "neutral";
}

export function debugBadgeTone(
  kind: "tool" | "skill_selected" | "skill_used",
): BadgeTone {
  if (kind === "tool") return "neutral";
  if (kind === "skill_selected") return "accent";
  return "success";
}
