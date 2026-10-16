"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useWorkspace } from "@/components/workspace";
import { ArrowLeft, Play, Trash2 } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { fmtBytes, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ErrorNote, Skeleton, Tabs } from "@/components/ui/misc";
import { DatasetExplorer } from "@/components/explorer";
import { MissingValues } from "@/components/missing-values";
import { DataGrid } from "@/components/data-grid";
import { ColumnTable, QualitySummary } from "@/components/dataset-profile";
import { StatusBadge } from "@/components/status";
import { DeleteDatasetDialog } from "@/components/delete-dataset";

export default function DatasetDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: d, error } = useApi<any>(`/datasets/${id}`);
  const { data: preview } = useApi<any>(`/datasets/${id}/preview?limit=100`);
  const [del, setDel] = useState<any | null>(null);
  const [tab, setTab] = useState<"overview" | "explore" | "missing">("overview");
  const { setCurrent } = useWorkspace();
  useEffect(() => { if (d) setCurrent({ datasetId: d.id, datasetName: d.name }); }, [d?.id]); // eslint-disable-line
  if (error) return <ErrorNote message={error} />;
  if (!d) return <Skeleton className="h-96" />;
  const types = Object.fromEntries(d.profile.columns.map((c: any) => [c.name, c.semantic_type.replace("_", " ")]));
  return (
    <div className="space-y-5 animate-in">
      <Link href="/datasets" className="inline-flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg"><ArrowLeft className="size-3.5" /> Datasets</Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="flex items-center gap-2 text-[26px] font-semibold tracking-tight">{d.name}{d.is_synthetic && <Badge tone="warning">Synthetic demo data</Badge>}</h1>
          <p className="mt-1 text-[13px] text-fg-3">{d.original_filename} · {fmtBytes(d.size_bytes)} · {d.n_rows.toLocaleString()} rows × {d.n_cols} columns · uploaded {timeAgo(d.created_at)} · SHA-256 <span className="font-mono">{d.sha256.slice(0, 12)}…</span></p></div>
        <div className="flex gap-2"><Button variant="secondary" onClick={() => setDel(d)}><Trash2 /> Delete</Button><Button asChild><Link href={`/new?dataset=${d.id}`}><Play /> Analyse</Link></Button></div>
      </div>
      {d.cleaning_log?.length > 0 && <Card className="p-4 text-[13px]"><div className="font-medium text-fg">Cleaning history</div>{d.cleaning_log.map((c: any, i: number) => <div key={i} className="text-fg-2">From <Link className="text-accent-text" href={`/datasets/${c.from_dataset}`}>{c.from_dataset}</Link>: {c.operations.map((o: any) => `${o.op}${o.column ? ` (${o.column})` : ""}${o.rows_removed !== undefined ? `, ${o.rows_removed} rows removed` : ""}${o.values_changed !== undefined ? `, ${o.values_changed} values changed` : ""}${o.cells_filled !== undefined ? `, ${o.cells_filled} cells filled by ${o.method}` : ""}`).join("; ")}</div>)}</Card>}
      <Tabs value={tab} onChange={setTab} items={[{ value: "overview", label: "Overview" }, { value: "explore", label: "Explore" }, { value: "missing", label: "Missing values", count: d.profile.columns.filter((c: any) => c.missing > 0).length }]} />
      {tab === "explore" && <DatasetExplorer id={d.id} />}
      {tab === "missing" && <Card><CardHeader><div><CardTitle>Missing values</CardTitle><CardDescription>{d.profile.missing_cells?.toLocaleString?.() ?? 0} missing cells ({((d.profile.missing_pct || 0) * 100).toFixed(2)}% of all cells)</CardDescription></div></CardHeader><CardContent><MissingValues dataset={d} onCleaned={(nd) => router.push(`/datasets/${nd.id}`)} /></CardContent></Card>}
      {tab === "overview" && <>
      <div className="grid gap-5 xl:grid-cols-5">
        <Card className="xl:col-span-3"><CardHeader><div><CardTitle>Preview</CardTitle><CardDescription>First {preview?.rows.length ?? 0} of {d.n_rows.toLocaleString()} rows</CardDescription></div></CardHeader>
          <CardContent>{preview ? <DataGrid columns={preview.columns} rows={preview.rows} types={types} maxHeight={460} dense /> : <Skeleton className="h-64" />}</CardContent></Card>
        <Card className="xl:col-span-2"><CardHeader><div><CardTitle>Data quality</CardTitle></div></CardHeader><CardContent><QualitySummary dataset={d} onCleaned={(nd) => router.push(`/datasets/${nd.id}`)} /></CardContent></Card>
      </div>
      <Card><CardHeader><div><CardTitle>Columns</CardTitle></div></CardHeader><CardContent><ColumnTable profile={d.profile} /></CardContent></Card>
      </>}
      <Card><CardHeader><div><CardTitle>Analysis history</CardTitle></div></CardHeader>
        <CardContent>{d.analyses.length ? <ul className="divide-y divide-border">{d.analyses.map((a: any) => <li key={a.id}><Link href={`/analyses/${a.id}`} className="flex items-center justify-between py-2 text-[13px] hover:text-accent-text"><span>{a.question}</span><span className="flex items-center gap-2 text-fg-3">{timeAgo(a.created_at)}<StatusBadge status={a.status} /></span></Link></li>)}</ul> : <p className="text-[13px] text-fg-3">No analyses yet.</p>}</CardContent></Card>
      <DeleteDatasetDialog ds={del} onClose={() => setDel(null)} onDeleted={() => router.push("/datasets")} />
    </div>
  );
}
