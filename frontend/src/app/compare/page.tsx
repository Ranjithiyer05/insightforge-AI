"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { DatasetCompare } from "@/components/dataset-compare";
import { Tabs } from "@/components/ui/misc";
import { ArrowLeftRight, Columns2 } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { cn, fmtNum, humanize, timeAgo } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, Label } from "@/components/ui/input";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";

const fmt = (m: any) => (m == null || m.value == null ? "—" : typeof m.value === "number" ? `${fmtNum(m.value, { money: m.unit === "currency" })}${m.unit === "%" ? "%" : ""}` : String(m.value));

function Side({ a }: { a: any }) {
  const r = a.result || {};
  return (
    <Card className="min-w-0">
      <CardHeader className="block">
        <Link href={`/analyses/${a.id}`} className="text-[15px] font-semibold leading-snug text-fg hover:text-accent-text">{a.question}</Link>
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
          <StatusBadge status={a.status} /><Badge tone="accent">{a.plan.task_label}</Badge><span>{a.dataset?.name}</span><span>· {timeAgo(a.created_at)}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-[13px]">
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-xl bg-surface-2 p-3"><div className="text-[11px] uppercase tracking-wide text-fg-3">Method used</div><div className="mt-0.5 font-medium text-fg">{r.final_strategy ? humanize(r.final_strategy) : "—"}</div></div>
          <div className="rounded-xl bg-surface-2 p-3"><div className="text-[11px] uppercase tracking-wide text-fg-3">Verification</div><div className="mt-1"><StatusBadge status={r.verification?.status || "—"} /></div>
            {r.verification?.counts && <div className="mt-1 text-[11.5px] text-fg-3 num">{r.verification.counts.pass ?? 0} passed · {r.verification.counts.fail ?? 0} failed</div>}</div>
          <div className="rounded-xl bg-surface-2 p-3"><div className="text-[11px] uppercase tracking-wide text-fg-3">Attempts</div><div className="mt-0.5 font-medium num text-fg">{r.attempts?.length ?? 0}</div></div>
          <div className="rounded-xl bg-surface-2 p-3"><div className="text-[11px] uppercase tracking-wide text-fg-3">Mode</div><div className="mt-0.5 font-medium text-fg">{humanize(a.agent_mode)}</div></div>
        </div>
        {r.executive_summary && <p className="leading-relaxed text-fg-2">{r.executive_summary}</p>}
        {r.findings?.length > 0 && <div><div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-fg-3">Findings</div>
          <ul className="space-y-1">{r.findings.map((f: any, i: number) => <li key={i} className="flex gap-2 text-fg"><span className="text-fg-3">•</span>{f.title}</li>)}</ul></div>}
      </CardContent>
    </Card>
  );
}

function Compare() {
  const sp = useSearchParams();
  const router = useRouter();
  const aId = sp.get("a"), bId = sp.get("b");
  const { data: list } = useApi<any[]>("/analyses?status=completed");
  const { data: a } = useApi<any>(aId ? `/analyses/${aId}` : null);
  const { data: b } = useApi<any>(bId ? `/analyses/${bId}` : null);
  const set = (k: "a" | "b", v: string) => { const p = new URLSearchParams(sp.toString()); v ? p.set(k, v) : p.delete(k); router.replace(`/compare?${p.toString()}`); };
  const keys = useMemo(() => Array.from(new Set([...Object.keys(a?.result?.metrics || {}), ...Object.keys(b?.result?.metrics || {})])), [a, b]);
  const opts = (list || []);
  const mode = sp.get("mode") === "datasets" ? "datasets" : "analyses";
  const header = (
    <>
      <PageHeader title="Compare" description={mode === "datasets" ? "Two datasets side by side: schema changes and which columns shifted." : "Put two finished analyses side by side: methods, verification and every metric they reported."} />
      <Tabs value={mode} onChange={(m) => router.replace(m === "datasets" ? "/compare?mode=datasets" : "/compare")} items={[{ value: "analyses", label: "Analyses" }, { value: "datasets", label: "Datasets" }]} />
    </>
  );
  if (mode === "datasets") return <div className="space-y-6 animate-in">{header}<DatasetCompare /></div>;
  return (
    <div className="space-y-6 animate-in">
      {header}
      <Card className="p-4">
        <div className="grid items-end gap-3 md:grid-cols-[1fr_auto_1fr]">
          <div className="space-y-1.5"><Label>Analysis A</Label><Select value={aId || ""} onChange={(e) => set("a", e.target.value)}><option value="">Select…</option>{opts.map((o) => <option key={o.id} value={o.id}>{o.question.slice(0, 80)} · {o.dataset_name}</option>)}</Select></div>
          <Button variant="ghost" size="icon" aria-label="Swap" onClick={() => { const p = new URLSearchParams(); if (bId) p.set("a", bId); if (aId) p.set("b", aId); router.replace(`/compare?${p}`); }}><ArrowLeftRight /></Button>
          <div className="space-y-1.5"><Label>Analysis B</Label><Select value={bId || ""} onChange={(e) => set("b", e.target.value)}><option value="">Select…</option>{opts.filter((o) => o.id !== aId).map((o) => <option key={o.id} value={o.id}>{o.question.slice(0, 80)} · {o.dataset_name}</option>)}</Select></div>
        </div>
      </Card>
      {!aId || !bId ? <EmptyState icon={Columns2} title="Pick two analyses" description="Choose any two completed analyses. Re-runs and follow-ups of the same question are the most useful to compare." /> :
        !a || !b ? <Skeleton className="h-96" /> : (
          <>
            <div className="grid gap-5 lg:grid-cols-2"><Side a={a} /><Side a={b} /></div>
            {keys.length > 0 && (
              <Card>
                <CardHeader><CardTitle>Metrics</CardTitle></CardHeader>
                <CardContent>
                  <div className="overflow-auto rounded-xl border border-border">
                    <table className="w-full text-[13px]">
                      <thead className="bg-surface-2 text-left text-fg-2"><tr><th className="px-3 py-2 font-medium">Metric</th><th className="px-3 py-2 font-medium">A</th><th className="px-3 py-2 font-medium">B</th><th className="px-3 py-2 font-medium">B − A</th></tr></thead>
                      <tbody>{keys.map((k) => {
                        const ma = a.result.metrics?.[k], mb = b.result.metrics?.[k];
                        const both = typeof ma?.value === "number" && typeof mb?.value === "number";
                        const d = both ? mb.value - ma.value : null;
                        return <tr key={k} className="border-t border-border"><td className="px-3 py-2 text-fg-2">{humanize(k)}</td><td className="px-3 py-2 num">{fmt(ma)}</td><td className="px-3 py-2 num">{fmt(mb)}</td>
                          <td className={cn("px-3 py-2 num", d != null && d > 0 && "text-success", d != null && d < 0 && "text-danger")}>{d == null ? "—" : `${d > 0 ? "+" : ""}${fmtNum(d, { money: ma.unit === "currency" })}`}</td></tr>;
                      })}</tbody>
                    </table>
                  </div>
                  <p className="mt-2 text-[12px] text-fg-3">Differences are arithmetic only. They do not say whether one analysis is better; check each side's verification first.</p>
                </CardContent>
              </Card>
            )}
          </>
        )}
    </div>
  );
}

export default function ComparePage() {
  return <Suspense fallback={<Skeleton className="h-96" />}><Compare /></Suspense>;
}
