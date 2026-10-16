import { AlertTriangle, CheckCircle2, CircleDashed, Clock, Loader2, PencilLine, XCircle, MinusCircle } from "lucide-react";
import { Badge } from "./ui/badge";

const MAP: Record<string, { label: string; tone: any; icon: any }> = {
  draft: { label: "Draft", tone: "neutral", icon: PencilLine },
  queued: { label: "Queued", tone: "neutral", icon: Clock },
  running: { label: "Running", tone: "info", icon: Loader2 },
  completed: { label: "Completed", tone: "success", icon: CheckCircle2 },
  succeeded: { label: "Succeeded", tone: "success", icon: CheckCircle2 },
  passed: { label: "Verified", tone: "success", icon: CheckCircle2 },
  pass: { label: "Pass", tone: "success", icon: CheckCircle2 },
  needs_review: { label: "Needs review", tone: "warning", icon: AlertTriangle },
  weak: { label: "Weak result", tone: "warning", icon: AlertTriangle },
  warn: { label: "Warning", tone: "warning", icon: AlertTriangle },
  invalid: { label: "Invalid", tone: "danger", icon: XCircle },
  failed: { label: "Failed", tone: "danger", icon: XCircle },
  fail: { label: "Fail", tone: "danger", icon: XCircle },
  skip: { label: "Skipped", tone: "neutral", icon: MinusCircle },
  not_run: { label: "Not verified", tone: "neutral", icon: CircleDashed },
  validated: { label: "Validated", tone: "success", icon: CheckCircle2 },
  candidate: { label: "Candidate", tone: "accent", icon: CircleDashed },
  rejected: { label: "Rejected", tone: "danger", icon: XCircle },
};

export function StatusBadge({ status, label }: { status?: string | null; label?: string }) {
  const m = MAP[status || ""] || { label: status || "Unknown", tone: "neutral", icon: CircleDashed };
  const Icon = m.icon;
  return (
    <Badge tone={m.tone}>
      <Icon className={status === "running" ? "animate-spin" : ""} />
      {label ?? m.label}
    </Badge>
  );
}

export function StatusDot({ status }: { status: string }) {
  const color = { completed: "bg-success", running: "bg-info pulse-dot", queued: "bg-fg-3", failed: "bg-danger", needs_review: "bg-warning", draft: "bg-fg-3" }[status] || "bg-fg-3";
  return <span className={`inline-block size-2 rounded-full ${color}`} />;
}
