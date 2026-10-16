"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { BrainCircuit, History, Pencil, Search, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { humanize, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { EmptyState, ErrorNote, PageHeader, Skeleton, Tabs } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";

function LessonDetail({ id, onChanged, onClose }: { id: string; onChanged: () => void; onClose: () => void }) {
  const { data: l, reload } = useApi<any>(`/lessons/${id}`);
  const [editing, setEditing] = useState(false);
  const [statement, setStatement] = useState("");
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  useEffect(() => { if (l) { setStatement(l.statement); setStatus(l.status); } }, [l]);
  if (!l) return <Skeleton className="h-64" />;
  const save = async () => {
    try { await api(`/lessons/${id}`, { method: "PATCH", json: { statement, status, reason } }); setEditing(false); reload(); onChanged(); } catch (e: any) { setErr(e.message); }
  };
  const del = async () => { await api(`/lessons/${id}`, { method: "DELETE" }); onChanged(); onClose(); };
  return (
    <div className="space-y-4 text-[13px]">
      <div className="flex flex-wrap items-center gap-2"><StatusBadge status={l.status} /><Badge tone={l.outcome === "success" ? "success" : "danger"}>{l.outcome === "success" ? "strategy worked" : "strategy failed"}</Badge>
        <Badge tone="outline">{humanize(l.task_type)}</Badge><Badge tone="outline">{humanize(l.strategy)}</Badge><Badge tone="outline">v{l.version}</Badge>{l.user_edited && <Badge tone="info">edited by you</Badge>}</div>
      {editing ? (
        <div className="space-y-2">
          <Label>Statement</Label><Textarea rows={3} value={statement} onChange={(e) => setStatement(e.target.value)} />
          <Label>Status</Label><Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="candidate">Candidate</option><option value="validated">Validated</option><option value="rejected">Rejected (never used)</option></Select>
          <Label>Reason for the change</Label><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Not applicable to our data" />
          {err && <ErrorNote message={err} />}
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button><Button onClick={save}>Save new version</Button></div>
        </div>
      ) : <p className="text-[14px] text-fg">{l.statement}</p>}
      <div className="rounded-lg border border-border bg-surface-2/60 p-3"><div className="flex items-center gap-1.5 font-medium text-fg"><ShieldCheck className="size-4" /> Why it is {l.status === "validated" ? "trusted" : "not yet trusted"}</div><p className="mt-1 text-fg-2">{l.trust_reason}</p>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">{[["Confidence", l.confidence], ["Verified evidence", l.verified_evidence], ["Contradictions", l.contradiction_count], ["Times reused", l.reuse_count]].map(([k, v]) => <div key={k as string}><div className="text-[11.5px] text-fg-3">{k}</div><div className="num font-semibold">{v}</div></div>)}</div></div>
      <div><div className="mb-1 font-medium text-fg">Conditions</div><div className="flex flex-wrap gap-1">{Object.entries(l.conditions || {}).map(([k, v]: any) => <Badge key={k} tone="outline">{humanize(k)} = {v}</Badge>)}</div></div>
      <div><div className="mb-1 font-medium text-fg">Evidence (provenance)</div>
        <ul className="space-y-1">{l.evidence.map((e: any, i: number) => <li key={i} className="flex flex-wrap items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-[12px]">
          {e.contradicts ? <Badge tone="danger">contradicts</Badge> : <Badge tone="success">supports</Badge>}{e.verified ? <Badge tone="success">verified</Badge> : <Badge tone="neutral">unverified</Badge>}
          {e.analysis_id ? <Link className="text-accent-text hover:underline" href={`/analyses/${e.analysis_id}`}>experiment {e.experiment_id}</Link> : <span>{e.experiment_id}</span>}
          {e.metric && <span className="text-fg-3">{e.metric} = {typeof e.value === "number" ? e.value.toFixed(3) : e.value}</span>}<span className="text-fg-3">dataset {e.dataset_sha}</span><span className="ml-auto text-fg-3">{timeAgo(e.at)}</span></li>)}</ul></div>
      {l.usages?.length > 0 && <div><div className="mb-1 font-medium text-fg">Reuse history</div><ul className="space-y-1">{l.usages.map((u: any, i: number) => <li key={i} className="text-[12px] text-fg-2">{timeAgo(u.created_at)} · similarity {u.similarity} · {u.analysis_id ? <Link className="text-accent-text" href={`/analyses/${u.analysis_id}`}>analysis</Link> : "evaluation"} · {u.effect}</li>)}</ul></div>}
      <div><div className="mb-1 flex items-center gap-1.5 font-medium text-fg"><History className="size-4" /> Version history</div><ul className="space-y-1">{l.versions.map((v: any) => <li key={v.version} className="text-[12px] text-fg-2">v{v.version} · {v.changed_by} · {v.reason} · status {v.snapshot.status}, confidence {v.snapshot.confidence} · {timeAgo(v.created_at)}</li>)}</ul></div>
      {!editing && <div className="flex justify-end gap-2 border-t border-border pt-3">
        {confirmDel ? <><span className="self-center text-fg-3">Delete permanently?</span><Button variant="ghost" onClick={() => setConfirmDel(false)}>No</Button><Button variant="danger" onClick={del}>Delete</Button></> :
          <><Button variant="ghost" onClick={() => setConfirmDel(true)}><Trash2 /> Delete</Button><Button variant="secondary" onClick={() => setEditing(true)}><Pencil /> Correct</Button></>}
      </div>}
    </div>
  );
}

function MemoryPage() {
  const sp = useSearchParams();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<string | null>(sp.get("lesson"));
  const { data, loading, reload } = useApi<any[]>(`/lessons?${new URLSearchParams({ ...(q ? { q } : {}), ...(status ? { status } : {}) })}`);
  return (
    <div className="animate-in">
      <PageHeader title="Learning memory" description="Lessons distilled from your experiments. Candidates become validated only after verified evidence on at least two datasets with few contradictions. Lessons only re-order strategies; they never replace computed results." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs"><Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-3" /><Input className="pl-8" placeholder="Search lessons" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Tabs value={status} onChange={setStatus} items={[{ value: "", label: "All" }, { value: "validated", label: "Validated" }, { value: "candidate", label: "Candidates" }, { value: "rejected", label: "Rejected" }]} />
      </div>
      {loading ? <Skeleton className="h-64" /> : !data?.length ? <EmptyState icon={BrainCircuit} title="No lessons yet" description="Lessons are recorded automatically after each verified experiment." /> : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.map((l) => (
            <button key={l.id} onClick={() => setOpen(l.id)} className="rounded-xl border border-border bg-surface p-4 text-left shadow-xs transition hover:border-accent/40">
              <div className="flex flex-wrap items-center gap-1.5"><StatusBadge status={l.status} /><Badge tone={l.outcome === "success" ? "success" : "danger"}>{l.outcome === "success" ? "worked" : "failed"}</Badge><Badge tone="outline">{humanize(l.task_type)}</Badge>
                <span className="ml-auto text-[11.5px] text-fg-3">reused {l.reuse_count}× · {timeAgo(l.updated_at)}</span></div>
              <p className="mt-2 line-clamp-3 text-[13px] text-fg">{l.statement}</p>
              <div className="mt-2 text-[12px] text-fg-3">confidence {l.confidence} · {l.verified_evidence} verified experiment(s) · {l.distinct_datasets} dataset(s) · {l.contradiction_count} contradiction(s)</div>
            </button>
          ))}
        </div>
      )}
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        {open && <DialogContent title="Lesson details" description="Inspect evidence, correct the lesson, or delete it." wide><LessonDetail id={open} onChanged={reload} onClose={() => setOpen(null)} /></DialogContent>}
      </Dialog>
      <Card className="mt-6"><CardHeader><div><CardTitle>How lessons are used</CardTitle><CardDescription>Retrieval matches the task type, discrete conditions (for example class imbalance or skew) and a numeric dataset fingerprint. Only validated lessons with similarity ≥ 0.55 can change the strategy order, and the chosen strategy is still executed and verified.</CardDescription></div></CardHeader></Card>
    </div>
  );
}

export default function Page() { return <Suspense><MemoryPage /></Suspense>; }
