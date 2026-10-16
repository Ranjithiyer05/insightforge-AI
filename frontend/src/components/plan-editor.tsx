"use client";
import { useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, Bot, CheckCircle2, Cpu, ListChecks, Play } from "lucide-react";
import { api } from "@/lib/api";
import { cn, humanize } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input, Label, Select } from "./ui/input";
import { ErrorNote } from "./ui/misc";

const TASKS = ["descriptive", "comparison", "hypothesis_test", "classification", "regression", "forecasting", "segmentation", "anomaly_detection", "profit_change"];
const COLUMN_KEYS = ["target", "outcome", "group", "value_col", "date_col", "revenue_col", "cost_col", "unit_cost_col", "profit_col", "product_col", "quantity_col", "discount_col", "unit_price_col"];
const LIST_KEYS = ["features", "numeric", "categorical"];
const KEY_LABELS: Record<string, string> = {
  target: "Target to predict", outcome: "Outcome variable", group: "Group / second variable", value_col: "Measure", date_col: "Date column", revenue_col: "Revenue",
  cost_col: "Total cost", unit_cost_col: "Unit cost", profit_col: "Profit", product_col: "Product", quantity_col: "Quantity", discount_col: "Discount", unit_price_col: "Unit price",
  features: "Features", numeric: "Numeric columns", categorical: "Categorical columns", freq: "Frequency", horizon: "Forecast horizon", design: "Test design", alpha: "Significance level",
};

export function PlanEditor({ analysis, columns, onChange }: { analysis: any; columns: string[]; onChange: (a: any) => void }) {
  const plan = analysis.plan;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const edit = async (body: any) => {
    setBusy(true); setErr(null);
    try { onChange(await api(`/analyses/${analysis.id}/plan`, { method: "PATCH", json: body })); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const approve = async () => {
    setBusy(true); setErr(null);
    try { await api(`/analyses/${analysis.id}/approve`, { method: "POST" }); onChange({ ...analysis, status: "queued" }); } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  const move = (i: number, d: number) => {
    const s = [...plan.strategies];
    const j = i + d;
    if (j < 0 || j >= s.length) return;
    [s[i], s[j]] = [s[j], s[i]];
    edit({ strategies: s });
  };
  const params = plan.params || {};
  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <Card className="lg:col-span-3">
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2"><ListChecks className="size-4 text-accent-text" /> Proposed analysis plan</CardTitle>
            <CardDescription>Nothing has run yet. Review and edit the plan, then approve it.</CardDescription>
          </div>
          <Badge tone={plan.planner?.kind === "llm" ? "accent" : "neutral"}>{plan.planner?.kind === "llm" ? <Bot /> : <Cpu />}{plan.planner?.kind === "llm" ? "LLM-assisted planner" : "Deterministic planner"}</Badge>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="rounded-lg border border-accent/25 bg-accent-soft/40 p-3.5">
            <div className="text-[11.5px] font-medium uppercase tracking-wide text-accent-text">Objective</div>
            <p className="mt-1 text-[14px] text-fg">{plan.objective}</p>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[12px]">
              <Badge tone="accent">{plan.task_label}</Badge>
              <Badge tone="outline">Intent confidence {(plan.confidence * 100).toFixed(0)}%</Badge>
              {plan.reasons?.map((r: string) => <span key={r} className="text-fg-3">{r}</span>)}
            </div>
          </div>
          {!plan.feasible && (
            <div className="rounded-lg border border-danger/30 bg-danger-soft p-3 text-[13px] text-danger">
              <div className="flex items-center gap-2 font-medium"><AlertTriangle className="size-4" /> This dataset cannot answer the question as planned</div>
              <ul className="mt-1 list-disc pl-5">{plan.missing_requirements.map((m: string) => <li key={m}>Missing: {m}</li>)}</ul>
              <p className="mt-1 text-[12px]">Pick different columns or task type below, or upload data that includes the missing fields.</p>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Analysis type</Label>
              <Select value={plan.task_type} onChange={(e) => edit({ task_type: e.target.value })} disabled={busy}>
                {TASKS.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
              </Select>
            </div>
            {Object.entries(params).filter(([k]) => COLUMN_KEYS.includes(k)).map(([k, v]) => (
              <div key={k} className="space-y-1.5">
                <Label>{KEY_LABELS[k] || humanize(k)}</Label>
                <Select value={(v as string) ?? ""} onChange={(e) => edit({ params: { [k]: e.target.value || null } })} disabled={busy}>
                  <option value="">— none —</option>
                  {columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </div>
            ))}
            {"horizon" in params && <div className="space-y-1.5"><Label>Forecast horizon (periods)</Label><Input type="number" min={1} max={24} defaultValue={params.horizon ?? ""} onBlur={(e) => edit({ params: { horizon: e.target.value ? Number(e.target.value) : null } })} /></div>}
            {"freq" in params && <div className="space-y-1.5"><Label>Frequency</Label><Select value={params.freq} onChange={(e) => edit({ params: { freq: e.target.value } })}>{[["D", "Daily"], ["W", "Weekly"], ["MS", "Monthly"], ["QS", "Quarterly"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></div>}
            {"design" in params && <div className="space-y-1.5"><Label>Test design</Label><Select value={params.design} onChange={(e) => edit({ params: { design: e.target.value } })}>{["numeric_categorical", "categorical_categorical", "numeric_numeric"].map((v) => <option key={v} value={v}>{humanize(v)}</option>)}</Select></div>}
          </div>
          {Object.entries(params).filter(([k, v]) => LIST_KEYS.includes(k) && Array.isArray(v)).map(([k, v]) => (
            <div key={k} className="space-y-1.5">
              <Label>{KEY_LABELS[k]} ({(v as string[]).length} selected)</Label>
              <div className="flex flex-wrap gap-1.5">
                {columns.map((c) => {
                  const on = (v as string[]).includes(c);
                  const excluded = (params.excluded_features || []).includes(c);
                  return <button key={c} disabled={busy} onClick={() => edit({ params: { [k]: on ? (v as string[]).filter((x) => x !== c) : [...(v as string[]), c] } })}
                    className={cn("rounded-md border px-2 py-0.5 text-[12px] transition", on ? "border-accent/40 bg-accent-soft text-accent-text" : "border-border text-fg-3 hover:text-fg", excluded && !on && "line-through decoration-warning")}
                    title={excluded ? "Excluded automatically (identifier or possible leakage)" : undefined}>{c}</button>;
                })}
              </div>
              {params.excluded_features?.length > 0 && <p className="text-[11.5px] text-fg-3">Struck-through columns were excluded automatically as identifiers or possible leakage: {params.excluded_features.join(", ")}.</p>}
            </div>
          ))}
          {plan.assumptions?.length > 0 && (
            <div className="space-y-1"><Label>Assumptions</Label><ul className="space-y-1 text-[13px] text-fg-2">{plan.assumptions.map((a: string) => <li key={a} className="flex gap-2"><span className="text-fg-3">•</span>{a}</li>)}</ul></div>
          )}
          {err && <ErrorNote message={err} />}
        </CardContent>
      </Card>

      <div className="space-y-6 lg:col-span-2">
        <Card>
          <CardHeader><div><CardTitle>Execution steps</CardTitle><CardDescription>{plan.steps.length} steps · {plan.estimated_sandbox_runs.min}–{plan.estimated_sandbox_runs.max} sandboxed code runs</CardDescription></div></CardHeader>
          <CardContent>
            <ol className="space-y-2.5">
              {plan.steps.map((s: any, i: number) => (
                <li key={s.key + i} className="flex gap-3">
                  <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[11px] font-semibold num text-fg-2">{i + 1}</span>
                  <div><div className="text-[13px] font-medium text-fg">{s.title} <Badge tone="outline" className="ml-1">{s.kind}</Badge></div><div className="text-[12px] text-fg-3">{s.description}</div></div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Strategies and retries</CardTitle><CardDescription>Tried in order. Weak or invalid results trigger a diagnosed retry with a justified alternative.</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <ol className="space-y-1.5">
              {plan.strategies.map((s: string, i: number) => (
                <li key={s} className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5 text-[13px]">
                  <span className="num text-fg-3">{i + 1}.</span><span className="flex-1 font-medium text-fg">{humanize(s)}</span>
                  <Button size="icon-sm" variant="ghost" onClick={() => move(i, -1)} disabled={i === 0 || busy} aria-label="Move up"><ArrowUp /></Button>
                  <Button size="icon-sm" variant="ghost" onClick={() => move(i, 1)} disabled={i === plan.strategies.length - 1 || busy} aria-label="Move down"><ArrowDown /></Button>
                </li>
              ))}
            </ol>
            {plan.strategies_locked && <p className="text-[11.5px] text-fg-3">You set this order, so memory will not re-rank it.</p>}
            <div className="flex items-center gap-3">
              <Label className="shrink-0">Retry budget</Label>
              <Select value={plan.retry_budget} onChange={(e) => edit({ retry_budget: Number(e.target.value) })} className="w-24">{[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</Select>
            </div>
          </CardContent>
        </Card>
        <div className="flex gap-2">
          <Button size="lg" className="flex-1" onClick={approve} disabled={busy || !plan.feasible}><Play /> Approve and run</Button>
        </div>
        <p className="flex items-center gap-1.5 text-[12px] text-fg-3"><CheckCircle2 className="size-3.5" /> Code runs in an isolated sandbox with no network access, time and memory limits.</p>
      </div>
    </div>
  );
}
