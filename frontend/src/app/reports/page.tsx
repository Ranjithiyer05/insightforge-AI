"use client";
import Link from "next/link";
import { FileText, ShieldCheck } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { timeAgo } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";

export default function Reports() {
  const { data, loading } = useApi<any[]>("/analyses");
  const done = (data || []).filter((a) => ["completed", "needs_review"].includes(a.status));
  return (
    <div className="animate-in">
      <PageHeader title="Reports" description="Reports generated from completed analyses. Each one links every finding to computed evidence." />
      {loading ? <Skeleton className="h-64" /> : !done.length ? <EmptyState icon={FileText} title="No reports yet" description="Reports appear when an analysis completes." action={<Button asChild size="sm"><Link href="/new">Start an analysis</Link></Button>} /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {done.map((a) => (
            <Link key={a.id} href={`/reports/${a.id}`}>
              <Card className="h-full p-4 transition hover:border-accent/40">
                <div className="mb-2 flex items-center justify-between"><span className="text-[12px] text-fg-3">{a.task_label} · {timeAgo(a.created_at)}</span><StatusBadge status={a.status} /></div>
                <div className="text-[14px] font-semibold leading-snug text-fg">{a.question}</div>
                <p className="mt-2 line-clamp-3 text-[12.5px] text-fg-3">{a.summary}</p>
                <div className="mt-3 flex items-center gap-1.5 text-[12px] text-fg-3"><ShieldCheck className="size-3.5" /> Verification: <StatusBadge status={a.verification || "not_run"} /></div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
