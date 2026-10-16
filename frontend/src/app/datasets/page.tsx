"use client";
import Link from "next/link";
import { useState } from "react";
import { Database, Lock, Plus, Search, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtBytes, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { EmptyState, PageHeader, Skeleton, Tabs } from "@/components/ui/misc";
import { DeleteDatasetDialog } from "@/components/delete-dataset";

export default function Datasets() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const { data, loading, reload } = useApi<any[]>(`/datasets?${new URLSearchParams({ ...(q ? { q } : {}), ...(kind ? { synthetic: kind === "synthetic" ? "true" : "false" } : {}) })}`);
  const { data: settings } = useApi<any>("/settings");
  const [del, setDel] = useState<any | null>(null);
  return (
    <div className="animate-in">
      <PageHeader title="My datasets" description="Datasets are private to your account and never sent to an LLM unless you allow sample rows in Settings." actions={<Button asChild><Link href="/new"><Plus /> Upload</Link></Button>} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs"><Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-3" /><Input className="pl-8" placeholder="Search datasets" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Tabs value={kind} onChange={setKind} items={[{ value: "", label: "All" }, { value: "uploaded", label: "Uploaded" }, { value: "synthetic", label: "Synthetic demos" }]} />
      </div>
      {loading ? <Skeleton className="h-64" /> : !data?.length ? <EmptyState icon={Database} title="No datasets" description="Upload a CSV or Excel file, or load a synthetic demo dataset." action={<Button size="sm" asChild><Link href="/new">Upload data</Link></Button>} /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((d) => (
            <Card key={d.id} className="flex flex-col p-4">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/datasets/${d.id}`} className="min-w-0"><div className="truncate text-[14px] font-semibold text-fg hover:text-accent-text">{d.name}</div><div className="truncate text-[12px] text-fg-3">{d.original_filename}</div></Link>
                <Button variant="ghost" size="icon-sm" onClick={() => setDel(d)} aria-label="Delete dataset"><Trash2 /></Button>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {d.is_synthetic && <Badge tone="warning">Synthetic</Badge>}
                <Badge tone="outline">{d.file_type.toUpperCase()}</Badge>
                {d.issues > 0 && <Badge tone="warning">{d.issues} quality warnings</Badge>}
                {d.cleaning_log?.length > 0 && <Badge tone="info">Cleaned copy</Badge>}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
                <div><div className="text-fg-3">Rows</div><div className="num font-medium text-fg">{d.n_rows.toLocaleString()}</div></div>
                <div><div className="text-fg-3">Columns</div><div className="num font-medium text-fg">{d.n_cols}</div></div>
                <div><div className="text-fg-3">Analyses</div><div className="num font-medium text-fg">{d.analyses}</div></div>
              </div>
              <div className="mt-auto flex items-center justify-between pt-3 text-[12px] text-fg-3"><span>{fmtBytes(d.size_bytes)} · uploaded {timeAgo(d.created_at)}</span>
                <Link href={`/new?dataset=${d.id}`} className="font-medium text-accent-text hover:underline">Analyse</Link></div>
            </Card>
          ))}
        </div>
      )}
      <Card className="mt-6 flex items-start gap-3 p-4 text-[13px] text-fg-2">
        <Lock className="mt-0.5 size-4 shrink-0 text-fg-3" />
        <div><div className="font-medium text-fg">Privacy and retention</div>
          {settings ? <>Files are stored on this server only, under a random id, visible only to your account. {settings.privacy.retention_days > 0 ? `Datasets are deleted automatically after ${settings.privacy.retention_days} days.` : "Datasets are kept until you delete them."} {settings.privacy.llm_sample_rows ? "Sample rows may be sent to the configured LLM." : "Only column names and types are ever sent to an LLM, and only if one is configured."}</> : "Loading…"}
        </div>
      </Card>
      <DeleteDatasetDialog ds={del} onClose={() => setDel(null)} onDeleted={reload} />
    </div>
  );
}
