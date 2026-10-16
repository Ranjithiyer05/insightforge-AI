"use client";
import { useEffect, useState } from "react";
import { BrainCircuit, ChevronRight, Code2, Database, FileText, GitBranch, Search, ShieldCheck, Terminal } from "lucide-react";
import { cn, fmtNum, humanize } from "@/lib/utils";
import { StatusBadge } from "./status";
import { CodeViewer } from "./code-viewer";
import { DataGrid } from "./data-grid";
import { Badge } from "./ui/badge";

const KIND_ICON: Record<string, any> = { profile: Search, memory: BrainCircuit, python: Code2, sql: Database, verify: ShieldCheck, decision: GitBranch, report: FileText };

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const t = new Date(since.endsWith("Z") || since.includes("+") ? since : since + "Z").getTime();
  return <span className="num">{Math.max(0, Math.round((now - t) / 1000))}s</span>;
}

function Outputs({ step }: { step: any }) {
  const o = step.outputs || {};
  if (step.kind === "memory") {
    return (
      <div className="space-y-2 text-[13px]">
        {o.mode && <div><span className="text-fg-3">Agent mode:</span> {o.mode}</div>}
        {o.effect?.map((e: string) => <div key={e} className="text-fg-2">• {e}</div>)}
        {o.strategy_order && <div><span className="text-fg-3">Strategy order:</span> {o.strategy_order.map(humanize).join(" → ")}</div>}
        {o.lessons?.length > 0 && <ul className="space-y-1">{o.lessons.map((l: any) => <li key={l.id} className="rounded-md border border-border px-2.5 py-1.5"><StatusBadge status={l.status} /> <span className="text-fg-2">{l.statement}</span> <span className="text-fg-3 text-[11.5px]">(similarity {l.similarity}, confidence {l.confidence})</span></li>)}</ul>}
        {o.note && <div className="text-fg-3">{o.note}</div>}
        {o.recorded_attempts !== undefined && <div>Recorded {o.recorded_attempts} experiment(s) as evidence in memory namespace.</div>}
      </div>
    );
  }
  if (step.kind === "decision") {
    return <div className="space-y-1 text-[13px]"><div className="text-fg">{o.justification}</div><div className="text-fg-3">Reason code: <code>{o.reason_code}</code> · retry budget remaining: {o.retry_budget_remaining}</div></div>;
  }
  if (step.kind === "verify") {
    const fails = (o.checks || []).filter((c: any) => c.status !== "pass");
    return <div className="space-y-1 text-[13px]">
      <div>Status <StatusBadge status={o.status} /> · {Object.entries(o.counts || {}).map(([k, v]) => `${v} ${k}`).join(" · ")}</div>
      {fails.map((c: any) => <div key={c.id} className="text-fg-2">• [{c.status}] {c.message}</div>)}
    </div>;
  }
  if (step.kind === "profile") {
    return <div className="space-y-1 text-[13px]"><div>{o.rows?.toLocaleString()} rows · columns used: {o.columns_used?.join(", ") || "—"}</div>
      {o.issues?.map((i: any, k: number) => <div key={k} className="text-fg-3">• {i.message}</div>)}</div>;
  }
  const metrics = Object.entries(o.metrics || {}).filter(([, m]: any) => m && !Array.isArray(m.value));
  return (
    <div className="space-y-3">
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {metrics.slice(0, 18).map(([k, m]: any) => <div key={k} className="rounded-md bg-surface-2 px-2 py-1"><div className="truncate font-mono text-[10.5px] text-fg-3">{k}</div><div className="text-[12.5px] num text-fg">{typeof m.value === "number" ? fmtNum(m.value) : String(m.value)}</div></div>)}
        </div>
      )}
      {o.warnings?.map((w: string) => <div key={w} className="text-[12.5px] text-warning">⚠ {w}</div>)}
      {o.notes?.map((w: string) => <div key={w} className="text-[12.5px] text-fg-3">{w}</div>)}
      {Object.entries(o.tables || {}).slice(0, 3).map(([n, t]: any) => <div key={n}><div className="mb-1 font-mono text-[11.5px] text-fg-3">{n} ({t.total_rows} rows)</div><DataGrid columns={t.columns} rows={t.rows.slice(0, 8)} maxHeight={220} dense /></div>)}
      {o.claims?.length > 0 && <div className="text-[12px] text-fg-3">{o.claims.length} numeric claims emitted for independent verification.</div>}
      {o.isolation && <div className="flex flex-wrap gap-1">{o.isolation.network_namespace && <Badge tone="success">no network</Badge>}<Badge tone="outline">{o.isolation.memory_mb} MB limit</Badge><Badge tone="outline">{o.isolation.timeout_s}s timeout</Badge><Badge tone="outline">audit hook</Badge><Badge tone="outline">static validation</Badge></div>}
    </div>
  );
}

export function StepTimeline({ steps }: { steps: any[] }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <ol className="relative space-y-2">
      {steps.map((s, i) => {
        const Icon = KIND_ICON[s.kind] || Terminal;
        const isOpen = open[s.id] ?? (s.status === "failed");
        return (
          <li key={s.id} className="relative">
            {i < steps.length - 1 && <span className="absolute left-[19px] top-10 h-[calc(100%-24px)] w-px bg-border" />}
            <div className={cn("rounded-xl border bg-surface transition", s.status === "running" ? "border-info/40 ring-2 ring-info/10" : s.status === "failed" ? "border-danger/30" : s.status === "needs_review" ? "border-warning/30" : "border-border")}>
              <button className="flex w-full items-center gap-3 px-3 py-2.5 text-left" onClick={() => setOpen({ ...open, [s.id]: !isOpen })} aria-expanded={isOpen}>
                <span className={cn("flex size-[22px] shrink-0 items-center justify-center rounded-md", s.status === "completed" ? "bg-success-soft text-success" : s.status === "failed" ? "bg-danger-soft text-danger" : s.status === "running" ? "bg-info-soft text-info" : "bg-surface-2 text-fg-3")}><Icon className="size-3.5" /></span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px] font-medium text-fg">{s.title}</div>
                  <div className="text-[11.5px] text-fg-3">{s.kind}{s.attempt > 1 ? ` · attempt ${s.attempt}` : ""}{s.duration_ms != null ? ` · ${(s.duration_ms / 1000).toFixed(2)}s` : ""}{s.cpu_s ? ` · ${s.cpu_s.toFixed(2)} CPU-s` : ""}
                    {s.status === "running" && s.started_at && <> · running for <Elapsed since={s.started_at} /></>}</div>
                </div>
                <StatusBadge status={s.status} />
                <ChevronRight className={cn("size-4 text-fg-3 transition", isOpen && "rotate-90")} />
              </button>
              {isOpen && (
                <div className="space-y-3 border-t border-border px-4 py-3 animate-in">
                  {s.rationale && <p className="text-[12.5px] text-fg-3"><span className="font-medium text-fg-2">Why: </span>{s.rationale}</p>}
                  {s.error && <div className="rounded-lg bg-danger-soft px-3 py-2 font-mono text-[12px] text-danger">{s.error}</div>}
                  {s.inputs && Object.keys(s.inputs).length > 0 && <details><summary className="cursor-pointer text-[12px] font-medium text-fg-2">Inputs</summary><pre className="mt-1 max-h-48 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-[11px] text-fg-2 scrollbar-thin">{JSON.stringify(s.inputs, null, 2)}</pre></details>}
                  <Outputs step={s} />
                  {s.code && <details><summary className="cursor-pointer text-[12px] font-medium text-fg-2">Generated code</summary><div className="mt-2"><CodeViewer code={s.code} maxHeight={360} /></div></details>}
                  {(s.stdout || s.stderr) && <details><summary className="cursor-pointer text-[12px] font-medium text-fg-2">Execution log</summary><pre className="mt-1 max-h-48 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-[11px] text-fg-2 scrollbar-thin">{s.stdout}{s.stderr && `\n[stderr]\n${s.stderr}`}</pre></details>}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
