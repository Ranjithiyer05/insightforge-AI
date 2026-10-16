"use client";
import Link from "next/link";
import { useState } from "react";
import { History, Plus, Search } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, PageHeader, Skeleton, Tabs } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";

export default function AnalysisHistory() {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const { data, loading } = useApi<any[]>(`/analyses?${new URLSearchParams({ ...(status ? { status } : {}), ...(q ? { q } : {}) })}`,
    { poll: (d) => d.some((a) => ["queued", "running"].includes(a.status)), interval: 3000 });
  return (
    <div className="animate-in">
      <PageHeader title="Analysis history" description="Every analysis with its plan, execution record, verification and report." actions={<Button asChild><Link href="/new"><Plus /> New analysis</Link></Button>} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs value={status} onChange={setStatus} items={[{ value: "", label: "All" }, { value: "completed", label: "Completed" }, { value: "needs_review", label: "Needs review" }, { value: "running", label: "Running" }, { value: "failed", label: "Failed" }, { value: "draft", label: "Drafts" }]} />
        <div className="relative w-full max-w-xs"><Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-3" /><Input className="pl-8" placeholder="Search questions" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>
      {loading ? <Skeleton className="h-64" /> : !data?.length ? <EmptyState icon={History} title="No analyses match" description="Start a new analysis to see it here." /> : (
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          <table className="w-full text-[13px]">
            <thead className="bg-surface-2 text-left text-fg-2"><tr>{["Question", "Type", "Dataset", "Status", "Verification", "Created"].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {data.map((a) => (
                <tr key={a.id} className="border-t border-border hover:bg-surface-2/50">
                  <td className="max-w-md px-4 py-2.5"><Link href={`/analyses/${a.id}`} className="font-medium text-fg hover:text-accent-text">{a.question}</Link>{a.parent_id && <Badge tone="outline" className="ml-2">follow-up</Badge>}</td>
                  <td className="px-4 py-2.5 text-fg-2">{a.task_label}</td>
                  <td className="px-4 py-2.5 text-fg-3">{a.dataset_name}</td>
                  <td className="px-4 py-2.5"><StatusBadge status={a.status} /></td>
                  <td className="px-4 py-2.5">{a.verification ? <StatusBadge status={a.verification} /> : <span className="text-fg-3">—</span>}</td>
                  <td className="px-4 py-2.5 text-fg-3 whitespace-nowrap">{timeAgo(a.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
