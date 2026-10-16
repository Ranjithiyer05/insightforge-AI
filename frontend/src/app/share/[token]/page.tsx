"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Eye, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { humanize, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { ResultsView, VerificationPanel } from "@/components/results";

export default function SharedReport() {
  const { token } = useParams<{ token: string }>();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api(`/public/share/${token}`).then(setD).catch((e) => setErr(e.message)); }, [token]);
  return (
    <div className="app-bg min-h-screen">
      <header className="border-b border-border/70 bg-surface/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-2.5"><div className="flex size-9 items-center justify-center rounded-xl grad-accent text-white"><Sparkles className="size-[18px]" /></div>
            <div className="leading-tight"><div className="text-[15px] font-semibold text-fg">InsightForge</div><div className="text-[11px] text-fg-3">Shared report</div></div></div>
          <Badge tone="neutral"><Eye /> Read-only</Badge>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
        {err && <ErrorNote message={err} />}
        {!d && !err && <><Skeleton className="h-20" /><Skeleton className="h-96" /></>}
        {d && (
          <>
            <div>
              <h1 className="text-[26px] font-semibold tracking-tight text-fg">{d.question}</h1>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px] text-fg-3">
                <StatusBadge status={d.status} />
                {d.task_label && <Badge tone="accent">{d.task_label}</Badge>}
                {d.dataset?.name && <span>{d.dataset.name} · {d.dataset.n_rows?.toLocaleString()} rows</span>}
                {d.dataset?.is_synthetic && <Badge tone="warning">Synthetic demo data</Badge>}
                {d.result.final_strategy && <span>· method: {humanize(d.result.final_strategy)}</span>}
                <span>· {timeAgo(d.created_at)}</span>
              </div>
            </div>
            <ResultsView report={{ ...d.result, task_type: d.task_type }} />
            {d.result.verification && (
              <section className="space-y-3">
                <h2 className="flex items-center gap-2 text-[17px] font-semibold text-fg"><ShieldCheck className="size-5 text-success" /> Independent verification</h2>
                <VerificationPanel verification={d.result.verification} />
              </section>
            )}
            <p className="pt-4 text-center text-[12px] text-fg-3">Produced with InsightForge AI. Numbers were recomputed from the source data by an independent verifier. <Link href="/login" className="text-accent-text hover:underline">Run your own analysis</Link></p>
          </>
        )}
      </main>
    </div>
  );
}
