"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Beaker, FlaskConical, Play, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtNum, humanize, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Label } from "@/components/ui/input";
import { EmptyState, ErrorNote, PageHeader, Skeleton, Tabs } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";

const HEADLINE = ["balanced_accuracy", "roc_auc", "r2", "p_value", "skill_vs_best_baseline", "silhouette", "profit_change_pct", "anomalies"];

function ExperimentList() {
  const [task, setTask] = useState("");
  const [status, setStatus] = useState("");
  const router = useRouter();
  const { data, loading } = useApi<any[]>(`/experiments?${new URLSearchParams({ ...(task ? { task_type: task } : {}), ...(status ? { status } : {}) })}`);
  const rerun = async (aid: string) => { const b = await api(`/analyses/${aid}/rerun`, { method: "POST" }); router.push(`/analyses/${b.id}`); };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Select className="w-48" value={task} onChange={(e) => setTask(e.target.value)}><option value="">All task types</option>{["profit_change", "classification", "regression", "hypothesis_test", "forecasting", "comparison", "segmentation", "anomaly_detection", "descriptive"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</Select>
        <Tabs value={status} onChange={setStatus} items={[{ value: "", label: "All" }, { value: "succeeded", label: "Succeeded" }, { value: "weak", label: "Weak" }, { value: "invalid", label: "Invalid" }, { value: "failed", label: "Failed" }]} />
      </div>
      {loading ? <Skeleton className="h-64" /> : !data?.length ? <EmptyState icon={Beaker} title="No experiments yet" description="Each strategy attempt in an analysis is recorded here with its measured metrics." /> : (
        <div className="overflow-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-[13px]">
            <thead className="bg-surface-2 text-left text-fg-2"><tr>{["Experiment", "Strategy", "Outcome", "Verification", "Measured", "Failure / diagnosis", "Cost", ""].map((h) => <th key={h} className="px-3 py-2.5 font-medium whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {data.map((e) => {
                const k = HEADLINE.find((h) => e.metrics?.[h] !== undefined);
                return (
                  <tr key={e.id} className="border-t border-border align-top">
                    <td className="px-3 py-2.5"><Link href={`/analyses/${e.analysis_id}`} className="line-clamp-2 max-w-xs font-medium text-fg hover:text-accent-text">{e.question}</Link><div className="text-[11.5px] text-fg-3">{humanize(e.task_type)} · attempt {e.attempt}{e.retry_of ? " (retry)" : ""} · {timeAgo(e.created_at)}</div></td>
                    <td className="px-3 py-2.5 whitespace-nowrap">{humanize(e.strategy)}</td>
                    <td className="px-3 py-2.5"><StatusBadge status={e.status} /></td>
                    <td className="px-3 py-2.5"><StatusBadge status={e.verification?.status || "not_run"} /></td>
                    <td className="px-3 py-2.5 whitespace-nowrap num">{k ? <><span className="text-fg-3">{humanize(k)}</span> {fmtNum(e.metrics[k])}</> : "—"}</td>
                    <td className="max-w-sm px-3 py-2.5 text-[12.5px] text-fg-2">{e.failure_reason || e.diagnosis || "—"}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap text-[12px] text-fg-3 num">{e.cpu_s?.toFixed(2)} CPU-s<br />{((e.duration_ms || 0) / 1000).toFixed(1)}s wall</td>
                    <td className="px-3 py-2.5"><Button size="sm" variant="ghost" onClick={() => rerun(e.analysis_id)} title="Reproducible rerun of the analysis"><RefreshCw /></Button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Evaluations() {
  const { data, reload } = useApi<any[]>("/evaluations", { poll: (d) => d.some((r) => ["queued", "running"].includes(r.status)), interval: 3000 });
  const [nTrain, setNTrain] = useState(2);
  const [nTest, setNTest] = useState(2);
  const [err, setErr] = useState<string | null>(null);
  const start = async () => {
    setErr(null);
    try { await api("/evaluations", { method: "POST", json: { n_train: nTrain, n_test: nTest } }); reload(); } catch (e: any) { setErr(e.message); }
  };
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader><div><CardTitle className="flex items-center gap-2"><FlaskConical className="size-4 text-accent-text" /> Learning evaluation</CardTitle>
          <CardDescription>Measures whether memory helps. Four agent configurations run the same synthetic benchmark (known ground truth) with isolated memory: training tasks first, then unseen test tasks. Only test tasks are scored.</CardDescription></div></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 text-[13px] sm:grid-cols-2 lg:grid-cols-4">
            {[["1. Baseline", "No memory, no verifier in the loop"], ["2. Ordinary retrieval", "Reuses the most similar past success (unvalidated)"], ["3. Validated memory", "Failure-aware, validated lessons only"], ["4. + Verification", "Validated memory and independent verification in the retry loop"]].map(([t, d]) => (
              <div key={t} className="rounded-lg border border-border p-3"><div className="font-medium text-fg">{t}</div><div className="text-[12px] text-fg-3">{d}</div></div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1"><Label>Training seeds per task family</Label><Select className="w-28" value={nTrain} onChange={(e) => setNTrain(Number(e.target.value))}>{[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</Select></div>
            <div className="space-y-1"><Label>Test seeds per family</Label><Select className="w-28" value={nTest} onChange={(e) => setNTest(Number(e.target.value))}>{[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</Select></div>
            <Button onClick={start}><Play /> Run evaluation</Button>
            <span className="text-[12px] text-fg-3">Runs about {6 * (nTrain + nTest) * 4} tasks in the sandbox; this takes a few minutes.</span>
          </div>
          {err && <ErrorNote message={err} />}
        </CardContent>
      </Card>
      {data?.length ? (
        <div className="space-y-2">
          {data.map((r) => (
            <Link key={r.id} href={`/experiments/eval/${r.id}`} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 hover:border-accent/40">
              <StatusBadge status={r.status} />
              <div className="min-w-0 flex-1"><div className="text-[13.5px] font-medium text-fg">Evaluation · {r.config.n_train} train / {r.config.n_test} test seeds per family</div>
                <div className="truncate text-[12px] text-fg-3">{r.status === "running" ? r.progress || "Starting…" : r.error || r.conclusion}</div></div>
              <span className="text-[12px] text-fg-3">{timeAgo(r.created_at)}</span>
            </Link>
          ))}
        </div>
      ) : <EmptyState icon={FlaskConical} title="No evaluations yet" description="Run one to measure differences between the four agent configurations. The app makes no improvement claims without this evidence." />}
    </div>
  );
}

export default function Experiments() {
  const [tab, setTab] = useState<"exp" | "eval">("exp");
  return (
    <div className="animate-in">
      <PageHeader title="Experiments" description="Every strategy attempt with measured metrics, failure reasons and retries, plus controlled evaluations of the learning system." />
      <Tabs className="mb-5" value={tab} onChange={setTab} items={[{ value: "exp", label: "Experiment log" }, { value: "eval", label: "Learning evaluation" }]} />
      {tab === "exp" ? <ExperimentList /> : <Evaluations />}
      <p className="mt-6 text-[12px] text-fg-3"><Badge tone="outline">Note</Badge> Compute cost is measured as sandbox CPU-seconds. LLM token cost is shown when a provider is configured; deterministic mode has none.</p>
    </div>
  );
}
