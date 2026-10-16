"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, BrainCircuit, Columns2, Copy, Droplets, Link2, Share2, Unlink, CheckCircle2, Circle, Code2, Download, FileDown, FileText, Loader2, MessageSquarePlus, RefreshCw, Send, ShieldCheck, Sparkles, Table2, XCircle, AlertTriangle } from "lucide-react";
import { api, download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, humanize, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { ErrorNote, Skeleton, Tabs } from "@/components/ui/misc";
import { Dropdown, DropdownContent, DropdownItem, DropdownTrigger } from "@/components/ui/dropdown";
import { StatusBadge } from "@/components/status";
import { PlanEditor } from "@/components/plan-editor";
import { StepTimeline } from "@/components/timeline";
import { ResultsView, VerificationPanel } from "@/components/results";
import { CodeViewer } from "@/components/code-viewer";
import { useWorkspace } from "@/components/workspace";

type Tab = "results" | "timeline" | "code" | "verification" | "experiments";

function ProgressTracker({ plan, steps, status }: { plan: any; steps: any[]; status: string }) {
  // Map planned steps to actual executed steps by key (latest attempt wins). No simulated progress.
  const byKey: Record<string, any> = {};
  steps.forEach((s) => (byKey[s.key] = s));
  const done = plan.steps.filter((p: any) => byKey[p.key] && byKey[p.key].status !== "running").length;
  return (
    <Card>
      <CardHeader><div><CardTitle>Plan and progress</CardTitle><CardDescription>{done} of {plan.steps.length} planned steps finished · {steps.length} recorded steps</CardDescription></div></CardHeader>
      <CardContent>
        <ol className="space-y-2">
          {plan.steps.map((p: any, i: number) => {
            const s = byKey[p.key];
            const st = s?.status || (status === "failed" ? "skip" : "queued");
            const Icon = st === "completed" ? CheckCircle2 : st === "running" ? Loader2 : st === "failed" ? XCircle : st === "needs_review" ? AlertTriangle : Circle;
            return (
              <li key={p.key + i} className="flex items-start gap-2.5">
                <Icon className={cn("mt-0.5 size-4 shrink-0", st === "completed" ? "text-success" : st === "running" ? "animate-spin text-info" : st === "failed" ? "text-danger" : st === "needs_review" ? "text-warning" : "text-border-strong")} />
                <div className="min-w-0">
                  <div className={cn("text-[13px]", s ? "text-fg" : "text-fg-3")}>{p.title}</div>
                  {s && s.attempt > 1 && <div className="text-[11.5px] text-fg-3">attempt {s.attempt}</div>}
                </div>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}

function Attempts({ report, steps }: { report: any; steps: any[] }) {
  const attempts = report?.attempts || [];
  return (
    <div className="space-y-5">
      <div className="overflow-auto rounded-xl border border-border">
        <table className="w-full text-[13px]">
          <thead className="bg-surface-2 text-left text-fg-2"><tr>{["#", "Strategy", "Outcome", "Verification", "Diagnosis", "CPU-s", "Time"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody>
            {attempts.map((a: any) => (
              <tr key={a.id} className={cn("border-t border-border", a.strategy === report.final_strategy && "bg-accent-soft/30")}>
                <td className="px-3 py-2 num">{a.attempt}</td>
                <td className="px-3 py-2 font-medium">{humanize(a.strategy)}{a.strategy === report.final_strategy && <Badge tone="accent" className="ml-2">used in report</Badge>}</td>
                <td className="px-3 py-2"><StatusBadge status={a.status} /></td>
                <td className="px-3 py-2"><StatusBadge status={a.verification_status} /></td>
                <td className="max-w-md px-3 py-2 text-fg-2">{a.diagnosis || "—"}</td>
                <td className="px-3 py-2 num">{a.cpu_s}</td>
                <td className="px-3 py-2 num">{(a.duration_ms / 1000).toFixed(2)}s</td>
              </tr>
            ))}
            {!attempts.length && <tr><td colSpan={7} className="px-3 py-6 text-center text-fg-3">{steps.length ? "Attempts appear here as they finish." : "Not started."}</td></tr>}
          </tbody>
        </table>
      </div>
      {report?.lessons_used?.length > 0 && (
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><BrainCircuit className="size-4 text-accent-text" /> Experience retrieved for this analysis</CardTitle><CardDescription>Lessons can only re-order strategies. Every strategy is still executed and verified.</CardDescription></div></CardHeader>
          <CardContent className="space-y-2">
            {report.lessons_used.map((l: any) => (
              <Link key={l.id} href={`/memory?lesson=${l.id}`} className="block rounded-lg border border-border p-3 hover:bg-surface-2">
                <div className="flex items-center gap-2"><StatusBadge status={l.status} /><span className="text-[12px] text-fg-3">similarity {l.similarity} · confidence {l.confidence} · {l.support_count} supporting</span></div>
                <div className="mt-1 text-[13px] text-fg-2">{l.statement}</div>
              </Link>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

const FOLLOWUPS: Record<string, string[]> = {
  classification: ["Try a different model", "Which features matter most?", "Is the target imbalanced?"],
  regression: ["Try a different model", "Which features matter most?"],
  hypothesis_test: ["Try a different test", "Compare the groups' averages"],
  comparison: ["Is the difference statistically significant?", "Try a different test"],
  profit_change: ["Forecast profit for the next 3 months", "Compare profit by region", "Is the discount change significant?"],
  forecasting: ["Try a different method", "Detect anomalies in the series"],
  segmentation: ["Try a different number of segments", "Detect anomalies"],
  anomaly_detection: ["Segment the data", "Describe the dataset"],
  descriptive: ["Segment the data", "Detect anomalies"],
};

function DataHandling({ h }: { h: any }) {
  if (!h) return null;
  const cols = Object.entries(h.missing_by_column || {}) as [string, number][];
  return (
    <Card>
      <CardHeader><div><CardTitle className="flex items-center gap-2"><Droplets className="size-4 text-info" /> Missing values</CardTitle>
        <CardDescription>Counted from the raw file for the columns this analysis used.</CardDescription></div></CardHeader>
      <CardContent className="space-y-2.5 text-[13px]">
        {h.rows_with_missing === 0 ? <p className="flex items-center gap-1.5 text-success"><CheckCircle2 className="size-4" /> No missing values in the {h.columns_used.length} columns used.</p> : (
          <>
            <div className="flex items-baseline justify-between"><span className="text-fg-2">Rows affected</span><span className="num font-semibold text-fg">{h.rows_with_missing.toLocaleString()} <span className="font-normal text-fg-3">of {h.rows_total.toLocaleString()} ({((h.rows_with_missing / Math.max(h.rows_total, 1)) * 100).toFixed(1)}%)</span></span></div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full bg-info" style={{ width: `${Math.min(100, (h.rows_with_missing / Math.max(h.rows_total, 1)) * 100)}%` }} /></div>
            <ul className="space-y-1">{cols.map(([c, n]) => <li key={c} className="flex justify-between text-[12.5px]"><span className="truncate text-fg-2">{c}</span><span className="num text-fg-3">{n.toLocaleString()} missing</span></li>)}</ul>
          </>
        )}
        <p className="rounded-lg bg-surface-2 p-2.5 text-[12px] leading-relaxed text-fg-2"><span className="font-medium text-fg">How they were handled: </span>{h.policy}</p>
      </CardContent>
    </Card>
  );
}

function ShareDialog({ id }: { id: string }) {
  const { data, reload } = useApi<any>(`/analyses/${id}/share`);
  const [link, setLink] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const create = async () => {
    setErr(null);
    try { const r = await api(`/analyses/${id}/share`, { method: "POST" }); setLink(`${location.origin}${r.path}`); reload(); } catch (e: any) { setErr(e.message); }
  };
  const revoke = async () => { await api(`/analyses/${id}/share`, { method: "DELETE" }); setLink(null); reload(); };
  return (
    <Dialog>
      <DialogTrigger asChild><Button variant="secondary" size="sm"><Share2 /> Share</Button></DialogTrigger>
      <DialogContent title="Share a read-only report" description="Anyone with the link can view the findings, charts, metrics and verification. They cannot see your code, raw data rows, other analyses or your account.">
        <div className="space-y-3">
          {link ? (
            <div className="flex gap-2"><Input readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
              <Button variant="secondary" onClick={() => { navigator.clipboard?.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1500); }}><Copy /> {copied ? "Copied" : "Copy"}</Button></div>
          ) : data?.shared ? (
            <p className="text-[13px] text-fg-2">A link is active (created {timeAgo(data.created_at)}). For security the link is shown only once. Create a new one to replace it.</p>
          ) : <p className="text-[13px] text-fg-2">No link yet.</p>}
          {err && <ErrorNote message={err} />}
          <div className="flex justify-between gap-2">
            {data?.shared ? <Button variant="ghost" onClick={revoke}><Unlink /> Revoke link</Button> : <span />}
            <Button onClick={create}><Link2 /> {data?.shared ? "Create new link" : "Create link"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function Workspace() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { setCurrent } = useWorkspace();
  const { data: a, error, setData, reload } = useApi<any>(`/analyses/${id}`, { poll: (d) => ["queued", "running"].includes(d.status), interval: 1200 });
  const [tab, setTab] = useState<Tab>("timeline");
  const [followup, setFollowup] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (a?.dataset) setCurrent({ datasetId: a.dataset.id, datasetName: a.dataset.name }); }, [a?.dataset?.id]); // eslint-disable-line
  useEffect(() => { if (a && ["completed", "needs_review"].includes(a.status)) setTab((t) => (t === "timeline" ? "results" : t)); }, [a?.status]); // eslint-disable-line

  const codeSteps = useMemo(() => (a?.steps || []).filter((s: any) => s.code), [a]);
  if (error) return <ErrorNote message={error} />;
  if (!a) return <div className="space-y-4"><Skeleton className="h-16" /><Skeleton className="h-96" /></div>;

  const report = a.result || {};
  const running = ["queued", "running"].includes(a.status);
  const current = a.steps.find((s: any) => s.status === "running");
  const hasResults = ["completed", "needs_review"].includes(a.status) && report.findings;

  const ask = async () => {
    setBusy(true); setErr(null);
    try {
      const b = await api(`/analyses/${a.id}/followup`, { method: "POST", json: { question: followup } });
      router.push(`/analyses/${b.id}`);
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  const rerun = async () => {
    try { const b = await api(`/analyses/${a.id}/rerun`, { method: "POST" }); router.push(`/analyses/${b.id}`); } catch (e: any) { setErr(e.message); }
  };

  return (
    <div className="space-y-5 animate-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link href="/analyses" className="mb-2 inline-flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg"><ArrowLeft className="size-3.5" /> Analysis history</Link>
          <h1 className="text-[20px] font-semibold leading-snug tracking-tight text-fg sm:text-[22px]">{a.question}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px] text-fg-3">
            <StatusBadge status={a.status} />
            <Badge tone="accent">{a.plan.task_label}</Badge>
            {a.dataset && <Link href={`/datasets/${a.dataset.id}`} className="hover:text-fg">{a.dataset.name}</Link>}
            {a.dataset?.is_synthetic && <Badge tone="warning">Synthetic demo data</Badge>}
            <span>· {humanize(a.agent_mode)}</span><span>· {timeAgo(a.created_at)}</span>
            {a.parent_id && <Link href={`/analyses/${a.parent_id}`} className="text-accent-text hover:underline">· follow-up of earlier analysis</Link>}
          </div>
        </div>
        {a.status !== "draft" && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={rerun} disabled={running}><RefreshCw /> Reproduce</Button>
            {hasResults && <Button variant="secondary" size="sm" asChild><Link href={`/reports/${a.id}`}><FileText /> Report</Link></Button>}
            {hasResults && <ShareDialog id={a.id} />}
            {hasResults && <Button variant="secondary" size="sm" asChild><Link href={`/compare?a=${a.id}`}><Columns2 /> Compare</Link></Button>}
            <Dropdown>
              <DropdownTrigger asChild><Button size="sm" disabled={!hasResults && !codeSteps.length}><Download /> Export</Button></DropdownTrigger>
              <DropdownContent>
                <DropdownItem disabled={!hasResults} onSelect={() => download(`/analyses/${a.id}/report.pdf`)}><FileDown /> Report (PDF)</DropdownItem>
                <DropdownItem disabled={!hasResults} onSelect={() => download(`/analyses/${a.id}/tables.zip`)}><Table2 /> Tables (CSV zip)</DropdownItem>
                <DropdownItem onSelect={() => download(`/analyses/${a.id}/code.zip`)}><Code2 /> Analysis code (zip)</DropdownItem>
              </DropdownContent>
            </Dropdown>
          </div>
        )}
      </div>
      {err && <ErrorNote message={err} />}

      {a.status === "draft" ? (
        <PlanEditor analysis={a} columns={a.dataset?.profile?.columns?.map((c: any) => c.name) || (a.plan.required_columns ?? [])} onChange={(n) => { setData({ ...a, ...n }); if (n.status === "queued") reload(); }} />
      ) : (
        <>
          {running && (
            <div className="flex items-center gap-3 rounded-xl border border-info/30 bg-info-soft/60 px-4 py-3 text-[13.5px]">
              <Loader2 className="size-4 animate-spin text-info" />
              <div className="flex-1"><span className="font-medium text-fg">{a.status === "queued" ? "Queued" : "Running"}</span>
                <span className="text-fg-2">{current ? ` · ${current.title}` : a.status === "queued" ? " · waiting for a worker" : ""}</span></div>
              <span className="text-[12px] text-fg-3">Status updates come from the execution record, not an estimate.</span>
            </div>
          )}
          {a.status === "failed" && <ErrorNote message={a.error || "The analysis failed. Open the failed step for details."} />}
          {a.status === "needs_review" && (
            <div className="flex gap-2 rounded-xl border border-warning/30 bg-warning-soft/60 px-4 py-3 text-[13.5px] text-fg"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
              <span>The analysis finished, but verification or result quality checks flagged issues. Results are shown with warnings; review the Verification tab before relying on them.</span></div>
          )}
          <div className="grid gap-5 lg:grid-cols-12">
            <div className="space-y-5 lg:col-span-4 xl:col-span-3">
              <ProgressTracker plan={a.plan} steps={a.steps} status={a.status} />
              <Card>
                <CardHeader><div><CardTitle>Objective</CardTitle></div></CardHeader>
                <CardContent className="space-y-2 text-[13px] text-fg-2">
                  <p>{a.plan.objective}</p>
                  <div className="flex flex-wrap gap-1">{a.plan.required_columns.map((c: string) => <Badge key={c} tone="outline">{c}</Badge>)}</div>
                  {report.final_strategy && <p className="text-fg-3">Final strategy: <span className="font-medium text-fg">{humanize(report.final_strategy)}</span></p>}
                  {report.verification && <p className="flex items-center gap-1.5"><ShieldCheck className="size-4 text-fg-3" /> Verification <StatusBadge status={report.verification.status} /></p>}
                </CardContent>
              </Card>
              <DataHandling h={report.data_handling} />
            </div>
            <div className="min-w-0 space-y-4 lg:col-span-8 xl:col-span-9">
              <Tabs<Tab> value={tab} onChange={setTab} items={[
                { value: "results", label: "Findings" }, { value: "timeline", label: "Execution timeline", count: a.steps.length },
                { value: "code", label: "Code", count: codeSteps.length }, { value: "verification", label: "Verification" },
                { value: "experiments", label: "Experiments", count: report.attempts?.length },
              ]} />
              {tab === "results" && (hasResults ? <ResultsView report={report} /> :
                <Card className="p-8 text-center text-[13.5px] text-fg-3">{running ? "Findings will appear once execution and verification finish. Follow progress in the execution timeline." : "No results were produced."}</Card>)}
              {tab === "timeline" && <StepTimeline steps={a.steps} />}
              {tab === "code" && (codeSteps.length ? <div className="space-y-4">{codeSteps.map((s: any) => (
                <div key={s.id}><div className="mb-1.5 flex items-center gap-2 text-[13px] font-medium text-fg">{s.title} <StatusBadge status={s.status} /></div><CodeViewer code={s.code} filename={`step${String(s.idx).padStart(2, "0")}_${s.key}.py`} /></div>
              ))}</div> : <p className="text-[13px] text-fg-3">No code has run yet.</p>)}
              {tab === "verification" && <VerificationPanel verification={report.verification} />}
              {tab === "experiments" && <Attempts report={report} steps={a.steps} />}
            </div>
          </div>
          {!running && (
            <Card className="relative overflow-hidden">
              <div className="pointer-events-none absolute -right-20 -top-20 size-56 rounded-full bg-accent/10 blur-3xl" />
              <CardContent className="relative pt-5">
                <div className="flex items-center gap-3">
                  <div className="flex size-9 items-center justify-center rounded-xl grad-accent text-white"><MessageSquarePlus className="size-4" /></div>
                  <div><div className="text-[14.5px] font-semibold text-fg">Ask a follow-up</div>
                    <div className="text-[12.5px] text-fg-3">Builds on this analysis: same dataset and settings unless your question asks for something different. You review the plan before it runs.</div></div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(FOLLOWUPS[a.plan.task_type] || []).map((q) => (
                    <button key={q} onClick={() => setFollowup(q)} className="rounded-full border border-border bg-surface px-3 py-1 text-[12.5px] text-fg-2 transition hover:border-accent/40 hover:bg-accent-soft/40 hover:text-fg">{q}</button>
                  ))}
                </div>
                <div className="mt-3 flex gap-2">
                  <Textarea rows={2} value={followup} onChange={(e) => setFollowup(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && followup.trim().length >= 4) ask(); }}
                    placeholder="e.g. Why did Trail Running Shoe costs rise?  ·  Try a different model" className="flex-1" />
                  <Button onClick={ask} disabled={busy || followup.trim().length < 4} className="self-end"><Send /> Plan follow-up</Button>
                </div>
                {a.children?.length > 0 && (
                  <div className="mt-4 border-t border-border pt-3">
                    <div className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wide text-fg-3">Follow-ups and re-runs</div>
                    <ul className="space-y-1">{a.children.map((c: any) => (
                      <li key={c.id}><Link href={`/analyses/${c.id}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] hover:bg-surface-2"><Sparkles className="size-3.5 text-accent-text" /><span className="flex-1 truncate text-fg">{c.question}</span><StatusBadge status={c.status} /></Link></li>
                    ))}</ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
