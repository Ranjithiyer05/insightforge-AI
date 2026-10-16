"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Code2, FileDown, Printer, Table2 } from "lucide-react";
import { download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { humanize } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { ResultsView, VerificationPanel } from "@/components/results";
import { StatusBadge } from "@/components/status";

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data: a, error } = useApi<any>(`/analyses/${id}`);
  if (error) return <ErrorNote message={error} />;
  if (!a) return <Skeleton className="h-96" />;
  const r = a.result;
  if (!r?.findings) return <ErrorNote message="This analysis has no report yet." />;
  const repro = r.reproducibility || {};
  return (
    <div className="mx-auto max-w-5xl space-y-6 animate-in">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link href={`/analyses/${a.id}`} className="inline-flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg"><ArrowLeft className="size-3.5" /> Back to workspace</Link>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => window.print()}><Printer /> Print</Button>
          <Button variant="secondary" size="sm" onClick={() => download(`/analyses/${a.id}/tables.zip`)}><Table2 /> CSV</Button>
          <Button variant="secondary" size="sm" onClick={() => download(`/analyses/${a.id}/code.zip`)}><Code2 /> Code</Button>
          <Button size="sm" onClick={() => download(`/analyses/${a.id}/report.pdf`)}><FileDown /> PDF</Button>
        </div>
      </div>
      <header className="rounded-2xl border border-border bg-surface p-6 shadow-card">
        <div className="text-[12px] font-medium uppercase tracking-wide text-accent-text">InsightForge analysis report</div>
        <h1 className="mt-1 text-[24px] font-semibold leading-tight tracking-tight text-fg">{a.question}</h1>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px] text-fg-3">
          <StatusBadge status={a.status} /><Badge tone="accent">{a.plan.task_label}</Badge><span>{a.dataset?.name} · {a.dataset?.n_rows?.toLocaleString()} rows</span>
          {a.dataset?.is_synthetic && <Badge tone="warning">Synthetic demo data: all records are invented</Badge>}
        </div>
        <p className="mt-3 text-[13.5px] text-fg-2"><span className="font-medium text-fg">Objective:</span> {r.objective}</p>
      </header>
      <ResultsView report={r} />
      <section><h3 className="mb-3 text-[15px] font-semibold text-fg">Independent verification</h3><VerificationPanel verification={r.verification} /></section>
      <section className="rounded-xl border border-border bg-surface p-5 text-[13px] text-fg-2">
        <h3 className="mb-2 text-[15px] font-semibold text-fg">Reproducibility</h3>
        <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          <div><dt className="inline text-fg-3">Dataset SHA-256: </dt><dd className="inline break-all font-mono text-[11.5px]">{a.dataset?.sha256}</dd></div>
          <div><dt className="inline text-fg-3">Final strategy: </dt><dd className="inline">{humanize(r.final_strategy)} after {r.attempts?.length} attempt(s)</dd></div>
          <div><dt className="inline text-fg-3">Random seed: </dt><dd className="inline">{repro.random_seed}</dd></div>
          <div><dt className="inline text-fg-3">Python: </dt><dd className="inline">{repro.python} · {Object.entries(repro.libraries || {}).map(([k, v]) => `${k} ${v}`).join(", ")}</dd></div>
          <div className="sm:col-span-2"><dt className="inline text-fg-3">Execution environment: </dt><dd className="inline">{repro.isolation}</dd></div>
        </dl>
        <p className="mt-3 text-fg-3">Use “Reproduce” in the workspace to re-run the identical plan, or download the code bundle to run it yourself.</p>
      </section>
    </div>
  );
}
