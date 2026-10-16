"use client";
import { AlertTriangle, CheckCircle2, CircleDashed, Lightbulb, ShieldCheck, XCircle } from "lucide-react";
import { cn, fmtNum, humanize } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "./ui/card";
import { ChartRenderer } from "./charts/chart-renderer";
import { DataGrid } from "./data-grid";

const KEY_METRICS: Record<string, string[]> = {
  profit_change: ["profit_current", "profit_change", "profit_change_pct", "margin_current_pct", "discount_rate_current_pct"],
  classification: ["balanced_accuracy", "roc_auc", "recall", "precision", "majority_baseline_accuracy"],
  regression: ["r2", "rmse", "mae", "baseline_rmse"],
  forecasting: ["next_period_forecast", "mae", "naive_mae", "skill_vs_best_baseline"],
  hypothesis_test: ["p_value", "effect_size", "statistic", "n"],
  comparison: ["top_mean", "bottom_mean", "groups", "kruskal_p"],
  segmentation: ["k", "silhouette"],
  anomaly_detection: ["anomalies", "anomaly_rate_pct"],
  descriptive: ["rows"],
};
const LABEL: Record<string, string> = {
  profit_current: "Profit (current month)", profit_change: "Profit change", profit_change_pct: "Profit change %", margin_current_pct: "Margin (current)",
  discount_rate_current_pct: "Avg discount (current)", balanced_accuracy: "Balanced accuracy", roc_auc: "ROC AUC", majority_baseline_accuracy: "Majority baseline",
  r2: "R² (test)", rmse: "RMSE (test)", mae: "MAE", baseline_rmse: "Baseline RMSE", next_period_forecast: "Next period forecast", naive_mae: "Naive MAE",
  skill_vs_best_baseline: "Skill vs naive", p_value: "p-value", effect_size: "Effect size", statistic: "Test statistic", n: "Sample size",
  top_mean: "Highest group mean", bottom_mean: "Lowest group mean", groups: "Groups", kruskal_p: "Kruskal p", k: "Segments", silhouette: "Silhouette",
  anomalies: "Anomalies", anomaly_rate_pct: "Anomaly rate", rows: "Rows",
};

export function MetricCards({ task, metrics }: { task: string; metrics: Record<string, any> }) {
  const keys = (KEY_METRICS[task] || []).filter((k) => metrics[k] && metrics[k].value !== null && metrics[k].value !== undefined);
  if (!keys.length) return null;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {keys.map((k) => {
        const m = metrics[k];
        const money = m.unit === "currency";
        const pct = m.unit === "%";
        const ci = m.ci95 || m.interval95;
        const v = m.value;
        return (
          <div key={k} className="lift relative overflow-hidden rounded-2xl border border-border bg-surface p-4 shadow-card">
            <div className={cn("absolute inset-x-0 top-0 h-[3px]", typeof v === "number" && k.includes("change") && v < 0 ? "bg-danger" : "grad-accent")} />
            <div className="text-[11.5px] font-medium uppercase tracking-wide text-fg-3">{LABEL[k] || humanize(k)}{m.name ? ` (${humanize(m.name)})` : ""}</div>
            <div className={cn("mt-1.5 text-[24px] font-semibold leading-tight tracking-tight num", typeof v === "number" && (k.includes("change") && v < 0) ? "text-danger" : "text-fg")}>
              {typeof v === "number" ? `${fmtNum(v, { money })}${pct ? "%" : ""}` : String(v)}
            </div>
            {ci && <div className="mt-0.5 text-[11.5px] text-fg-3 num">95% CI {fmtNum(ci[0], { money })} – {fmtNum(ci[1], { money })}</div>}
            {m.split && <div className="mt-0.5 text-[11px] text-fg-3">{m.split}</div>}
            {m.magnitude && <div className="mt-0.5 text-[11px] text-fg-3">{m.magnitude} effect</div>}
          </div>
        );
      })}
    </div>
  );
}

export function Findings({ report }: { report: any }) {
  const ev = (id: string) => {
    const v = report.verification?.verified_claims?.[id];
    return <Badge key={id} tone={v === true ? "success" : v === false ? "danger" : "outline"} className="font-mono text-[10.5px]">{v === true ? <CheckCircle2 /> : v === false ? <XCircle /> : null}{id}</Badge>;
  };
  return (
    <div className="space-y-3">
      {report.findings.map((f: any, i: number) => (
        <div key={i} className="rounded-xl border border-border bg-surface p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h4 className="text-[14.5px] font-semibold text-fg">{f.title}</h4>
            <div className="flex gap-1.5">
              <Badge tone={f.kind === "caution" ? "warning" : f.kind === "inference" ? "info" : "neutral"}>{f.kind}</Badge>
              <Badge tone="outline">confidence {f.confidence}</Badge>
              {f.verified === true && <Badge tone="success"><ShieldCheck /> verified</Badge>}
              {f.verified === false && <Badge tone="danger"><XCircle /> failed check</Badge>}
              {f.verified === null && <Badge tone="neutral"><CircleDashed /> not verified</Badge>}
            </div>
          </div>
          <p className="mt-1.5 text-[13.5px] leading-relaxed text-fg-2">{f.detail}</p>
          <div className="mt-2.5 flex flex-wrap items-center gap-1"><span className="text-[11px] text-fg-3">Evidence:</span>{f.evidence.map(ev)}</div>
        </div>
      ))}
    </div>
  );
}

export function ResultsView({ report }: { report: any }) {
  return (
    <div className="space-y-6">
      <MetricCards task={report.task_type} metrics={report.metrics} />
      <Card>
        <CardHeader><div><CardTitle>Executive summary</CardTitle><CardDescription>Written by: {report.narrative_source}</CardDescription></div></CardHeader>
        <CardContent><p className="text-[14px] leading-relaxed text-fg">{report.executive_summary}</p>
          {report.warnings?.map((w: string) => <div key={w} className="mt-3 flex gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[13px] text-warning"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{w}</div>)}
        </CardContent>
      </Card>
      <section>
        <h3 className="mb-3 text-[15px] font-semibold text-fg">Key findings</h3>
        <Findings report={report} />
      </section>
      {report.charts?.length > 0 && (
        <section>
          <h3 className="mb-3 text-[15px] font-semibold text-fg">Charts</h3>
          <div className="grid gap-4 xl:grid-cols-2">{report.charts.map((c: any) => <ChartRenderer key={c.id} spec={c} />)}</div>
        </section>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Lightbulb className="size-4 text-accent-text" /> Recommendations</CardTitle><CardDescription>Suggestions linked to observed evidence, not completed actions.</CardDescription></div></CardHeader>
          <CardContent className="space-y-2.5">
            {report.recommendations.length === 0 && <p className="text-[13px] text-fg-3">No recommendations.</p>}
            {report.recommendations.map((r: any, i: number) => (
              <div key={i} className="rounded-lg border border-border p-3">
                <div className="text-[13.5px] font-medium text-fg">{r.action}</div>
                <div className="mt-0.5 text-[12.5px] text-fg-3">{r.rationale}</div>
                <div className="mt-1.5 flex flex-wrap gap-1">{r.evidence.map((e: string) => <Badge key={e} tone="outline" className="font-mono text-[10.5px]">{e}</Badge>)}</div>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><AlertTriangle className="size-4 text-warning" /> Limitations and uncertainty</CardTitle></div></CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-[13px] text-fg-2">{report.limitations.map((l: string) => <li key={l} className="flex gap-2"><span className="text-fg-3">•</span>{l}</li>)}</ul>
            {report.data_quality?.length > 0 && <>
              <div className="mb-1.5 mt-4 text-[12.5px] font-medium text-fg-2">Data-quality warnings</div>
              <ul className="space-y-1 text-[12.5px] text-fg-3">{report.data_quality.map((q: any, i: number) => <li key={i}>• {q.message}</li>)}</ul>
            </>}
          </CardContent>
        </Card>
      </div>
      {Object.keys(report.tables || {}).length > 0 && (
        <section className="space-y-4">
          <h3 className="text-[15px] font-semibold text-fg">Result tables</h3>
          {Object.entries(report.tables).map(([name, t]: any) => (
            <div key={name}><div className="mb-1.5 font-mono text-[12px] text-fg-2">{name} <span className="text-fg-3">· {t.rows.length} rows</span></div><DataGrid columns={t.columns} rows={t.rows} maxHeight={300} dense /></div>
          ))}
        </section>
      )}
    </div>
  );
}

export function VerificationPanel({ verification }: { verification: any }) {
  if (!verification) return <p className="text-[13px] text-fg-3">Independent verification did not run in this agent mode.</p>;
  const groups: Record<string, any[]> = {};
  verification.checks.forEach((c: any) => (groups[c.category] = groups[c.category] || []).push(c));
  const icon = (s: string) => s === "pass" ? <CheckCircle2 className="size-4 text-success" /> : s === "fail" ? <XCircle className="size-4 text-danger" /> : s === "warn" ? <AlertTriangle className="size-4 text-warning" /> : <CircleDashed className="size-4 text-fg-3" />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface p-4">
        <ShieldCheck className={cn("size-6", verification.status === "passed" ? "text-success" : verification.status === "failed" ? "text-danger" : "text-warning")} />
        <div className="flex-1"><div className="text-[14px] font-semibold text-fg">Verification {verification.status === "passed" ? "passed" : verification.status === "failed" ? "failed" : "needs review"}</div>
          <div className="text-[12.5px] text-fg-3">{verification.engine}. Separate from any narrative text.</div></div>
        <div className="flex gap-1.5">{Object.entries(verification.counts).map(([k, v]: any) => <Badge key={k} tone={k === "pass" ? "success" : k === "fail" ? "danger" : k === "warn" ? "warning" : "neutral"}>{v} {k}</Badge>)}</div>
      </div>
      {Object.entries(groups).map(([cat, checks]) => (
        <div key={cat}>
          <div className="mb-1.5 text-[12px] font-medium uppercase tracking-wide text-fg-3">{humanize(cat)}</div>
          <ul className="divide-y divide-border rounded-xl border border-border bg-surface">
            {checks.map((c) => (
              <li key={c.id} className="flex items-start gap-2.5 px-3.5 py-2.5 text-[13px]">
                {icon(c.status)}<div className="flex-1 text-fg-2">{c.message}</div>
                {c.reported !== undefined && <span className="hidden font-mono text-[11px] text-fg-3 sm:block">{fmtNum(c.reported)} = {fmtNum(c.recomputed)}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
