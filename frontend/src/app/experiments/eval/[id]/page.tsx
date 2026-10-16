"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CheckCircle2, Minus, TrendingDown } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { cn, fmtNum, humanize } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { ChartRenderer } from "@/components/charts/chart-renderer";

const METRIC_LABEL: Record<string, string> = { correct: "Analytical correctness", valid: "Statistical validity", attempts: "Attempts per task", repeated_failures: "Repeated failures" };

export default function EvalDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: r, error } = useApi<any>(`/evaluations/${id}`, { poll: (d) => ["queued", "running"].includes(d.status), interval: 3000 });
  if (error) return <ErrorNote message={error} />;
  if (!r) return <Skeleton className="h-96" />;
  const res = r.results || {};
  const s = res.summary || {};
  const modes = Object.keys(s);
  const pct = (v: number) => `${(v * 100).toFixed(0)}%`;
  return (
    <div className="space-y-6 animate-in">
      <Link href="/experiments" className="inline-flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg"><ArrowLeft className="size-3.5" /> Experiments</Link>
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-[22px] font-semibold tracking-tight">Learning evaluation</h1><StatusBadge status={r.status} /></div>
      {["queued", "running"].includes(r.status) && <Card className="p-4 text-[13px] text-fg-2">Running: {res.progress || "starting…"}. Results appear when every configuration has finished.</Card>}
      {r.error && <ErrorNote message={r.error} />}
      {r.status === "completed" && <>
        <Card className={cn("p-5", res.comparisons?.some((c: any) => c.verdict === "improved") ? "border-success/30" : "")}>
          <div className="text-[12px] font-medium uppercase tracking-wide text-fg-3">Measured conclusion</div>
          <p className="mt-1 text-[15px] font-medium text-fg">{res.conclusion}</p>
          <p className="mt-2 text-[12.5px] text-fg-3">{res.protocol?.note} Families: {res.protocol?.families?.join(", ")}. {s[modes[0]]?.n_test_tasks} test tasks per configuration; improvement is claimed only when a paired bootstrap 95% CI excludes zero.</p>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Results on unseen test tasks</CardTitle><CardDescription>All values measured in this run.</CardDescription></div></CardHeader>
          <CardContent className="overflow-auto">
            <table className="w-full text-[13px]">
              <thead className="text-left text-fg-2"><tr className="border-b border-border">{["Configuration", "Completion", "Correctness", "Statistical validity", "Attempts / task", "Repeated failures", "Needs human review", "Time / task", "Sandbox CPU-s", "LLM tokens", "Planner accuracy"].map((h) => <th key={h} className="px-2 py-2 font-medium whitespace-nowrap">{h}</th>)}</tr></thead>
              <tbody>{modes.map((m) => { const x = s[m]; return (
                <tr key={m} className="border-b border-border/70"><td className="px-2 py-2 font-medium whitespace-nowrap">{x.label}</td><td className="px-2 py-2 num">{pct(x.task_completion)}</td><td className="px-2 py-2 num">{pct(x.correctness)}</td>
                  <td className="px-2 py-2 num">{pct(x.statistical_validity)}</td><td className="px-2 py-2 num">{x.mean_attempts.toFixed(2)}</td><td className="px-2 py-2 num">{x.repeated_failures}</td><td className="px-2 py-2 num">{x.human_interventions}</td>
                  <td className="px-2 py-2 num">{x.mean_seconds.toFixed(1)}s</td><td className="px-2 py-2 num">{x.sandbox_cpu_s.toFixed(1)}</td><td className="px-2 py-2 num">{x.llm_tokens}</td><td className="px-2 py-2 num">{pct(x.plan_accuracy)}</td></tr>); })}</tbody>
            </table>
          </CardContent>
        </Card>
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartRenderer spec={{ id: "q", kind: "bar", title: "Correctness and statistical validity by configuration (%)", x: "mode", unit: "%",
            data: modes.map((m) => ({ mode: s[m].label.replace("Validated memory + independent verification", "Validated + verified"), correctness: +(s[m].correctness * 100).toFixed(1), validity: +(s[m].statistical_validity * 100).toFixed(1) })),
            series: [{ key: "correctness", label: "Correctness" }, { key: "validity", label: "Statistical validity" }] }} />
          <ChartRenderer spec={{ id: "a", kind: "bar", title: "Mean attempts per test task (lower is more efficient)", x: "mode",
            data: modes.map((m) => ({ mode: s[m].label.replace("Validated memory + independent verification", "Validated + verified"), attempts: +s[m].mean_attempts.toFixed(2) })), series: [{ key: "attempts", label: "Attempts" }] }} />
        </div>
        <Card>
          <CardHeader><div><CardTitle>Paired differences versus baseline</CardTitle><CardDescription>Mean per-task difference with 95% bootstrap confidence interval.</CardDescription></div></CardHeader>
          <CardContent className="overflow-auto">
            <table className="w-full text-[13px]"><thead className="text-left text-fg-2"><tr className="border-b border-border">{["Configuration", "Metric", "Mean difference", "95% CI", "n", "Verdict"].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{res.comparisons.map((c: any, i: number) => (
                <tr key={i} className="border-b border-border/70"><td className="px-2 py-2">{s[c.mode]?.label}</td><td className="px-2 py-2">{METRIC_LABEL[c.metric]} <span className="text-fg-3">({c.better} is better)</span></td>
                  <td className="px-2 py-2 num">{c.mean_diff_vs_baseline >= 0 ? "+" : ""}{fmtNum(c.mean_diff_vs_baseline)}</td><td className="px-2 py-2 num">[{fmtNum(c.ci95[0])}, {fmtNum(c.ci95[1])}]</td><td className="px-2 py-2 num">{c.n}</td>
                  <td className="px-2 py-2">{c.verdict === "improved" ? <Badge tone="success"><CheckCircle2 /> improved</Badge> : c.verdict === "worse" ? <Badge tone="danger"><TrendingDown /> worse</Badge> : <Badge tone="neutral"><Minus /> no significant difference</Badge>}</td></tr>))}</tbody></table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Per-task results</CardTitle></div></CardHeader>
          <CardContent className="overflow-auto">
            <table className="w-full text-[12.5px]"><thead className="text-left text-fg-2"><tr className="border-b border-border">{["Configuration", "Phase", "Task", "Strategies tried", "Status", "Correct", "Valid", "Repeated failures"].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{modes.flatMap((m) => res.per_task[m].map((t: any) => (
                <tr key={m + t.task} className={cn("border-b border-border/60", t.phase === "train" && "text-fg-3")}><td className="px-2 py-1.5 whitespace-nowrap">{s[m].label}</td><td className="px-2 py-1.5">{t.phase}</td><td className="px-2 py-1.5">{t.family}</td>
                  <td className="px-2 py-1.5">{(t.strategies || []).map(humanize).join(" → ")}</td><td className="px-2 py-1.5">{t.status ? <StatusBadge status={t.status} /> : t.error}</td>
                  <td className="px-2 py-1.5">{t.correct ? "✓" : "✗"}</td><td className="px-2 py-1.5">{t.valid ? "✓" : "✗"}</td><td className="px-2 py-1.5 num">{t.repeated_failures ?? 0}</td></tr>)))}</tbody></table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Lessons each configuration learned</CardTitle><CardDescription>Snapshot taken before the isolated evaluation memory was cleared.</CardDescription></div></CardHeader>
          <CardContent className="grid gap-4 lg:grid-cols-2">{Object.entries(res.lessons_learned || {}).map(([m, ls]: any) => (
            <div key={m}><div className="mb-1.5 text-[13px] font-medium">{s[m]?.label} <span className="text-fg-3">({ls.length})</span></div>
              <ul className="space-y-1">{ls.length === 0 ? <li className="text-[12.5px] text-fg-3">No memory (baseline).</li> : ls.map((l: any, i: number) => <li key={i} className="flex gap-2 text-[12px] text-fg-2"><StatusBadge status={l.status} /><span>{l.statement}</span></li>)}</ul></div>))}</CardContent>
        </Card>
      </>}
    </div>
  );
}
