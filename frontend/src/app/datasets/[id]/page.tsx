"use client";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useWorkspace } from "@/components/workspace";
import { ArrowLeft, Download, GitBranch, Play, Trash2 } from "lucide-react";
import { download } from "@/lib/api";
import { PagedPreview } from "@/components/paged-preview";
import { QualityDashboard } from "@/components/quality-dashboard";
import { CleaningWorkspace } from "@/components/cleaning-workspace";
import { EdaView } from "@/components/eda-view";
import { AskData } from "@/components/ask-data";
import { ModelBuilder } from "@/components/model-builder";
import { Dropdown, DropdownContent, DropdownItem, DropdownTrigger } from "@/components/ui/dropdown";
import { useApi } from "@/lib/hooks";
import { fmtBytes, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ErrorNote, Skeleton, Tabs } from "@/components/ui/misc";
import { DatasetExplorer } from "@/components/explorer";
import { MissingValues } from "@/components/missing-values";
import { ColumnTable, QualitySummary } from "@/components/dataset-profile";
import { StatusBadge } from "@/components/status";
import { DeleteDatasetDialog } from "@/components/delete-dataset";

export default function Page() {
  return <Suspense fallback={<Skeleton className="h-96" />}><DatasetDetail /></Suspense>;
}

function DatasetDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: d, error } = useApi<any>(`/datasets/${id}`);
  const sp = useSearchParams();
  const [del, setDel] = useState<any | null>(null);
  type Tab = "overview" | "quality" | "clean" | "ask" | "model" | "insights" | "explore" | "missing";
  const [tab, setTabState] = useState<Tab>((sp.get("tab") as Tab) || "overview");
  const setTab = (t: Tab) => { setTabState(t); try { history.replaceState(null, "", `?tab=${t}`); } catch {} };
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
        <div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={() => setDel(d)}><Trash2 /> Delete</Button>
          <Dropdown><DropdownTrigger asChild><Button variant="secondary"><Download /> Export</Button></DropdownTrigger>
            <DropdownContent><DropdownItem onSelect={() => download(`/datasets/${d.id}/download?format=csv`)}>CSV</DropdownItem><DropdownItem onSelect={() => download(`/datasets/${d.id}/download?format=xlsx`)}>Excel (.xlsx)</DropdownItem></DropdownContent></Dropdown><Button asChild><Link href={`/new?dataset=${d.id}`}><Play /> Analyse</Link></Button></div>
      </div>
      {d.parent_id && <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[12.5px] text-fg-2"><GitBranch className="size-4 text-fg-3" /> Cleaned version with {d.cleaning_log.reduce((n: number, h: any) => n + h.operations.length, 0)} recorded steps. <button className="text-accent-text hover:underline" onClick={() => setTab("clean")}>See history and earlier versions</button></div>}
      <Tabs value={tab} onChange={setTab} items={[{ value: "overview", label: "Overview" }, { value: "quality", label: "Quality", count: d.issues }, { value: "clean", label: "Clean" },
        { value: "ask", label: "Ask" }, { value: "model", label: "Predict" }, { value: "insights", label: "Insights" }, { value: "explore", label: "Explore columns" }, { value: "missing", label: "Missing values", count: d.profile.columns.filter((c: any) => c.missing > 0).length }]} />
      {tab === "quality" && <QualityDashboard dataset={d} />}
      {tab === "clean" && <CleaningWorkspace dataset={d} onCleaned={(nd) => router.push(`/datasets/${nd.id}?tab=clean`)} />}
      {tab === "ask" && <AskData datasetId={d.id} />}
      {tab === "model" && <ModelBuilder dataset={d} />}
      {tab === "insights" && <EdaView datasetId={d.id} />}
      {tab === "explore" && <DatasetExplorer id={d.id} />}
      {tab === "missing" && <Card><CardHeader><div><CardTitle>Missing values</CardTitle><CardDescription>{d.profile.missing_cells?.toLocaleString?.() ?? 0} missing cells ({((d.profile.missing_pct || 0) * 100).toFixed(2)}% of all cells)</CardDescription></div></CardHeader><CardContent><MissingValues dataset={d} onCleaned={(nd) => router.push(`/datasets/${nd.id}`)} /></CardContent></Card>}
      {tab === "overview" && <>
      <div className="grid gap-5 xl:grid-cols-5">
        <Card className="xl:col-span-3"><CardHeader><div><CardTitle>Preview</CardTitle><CardDescription>{d.n_rows.toLocaleString()} rows; page through all of them</CardDescription></div></CardHeader>
          <CardContent><PagedPreview datasetId={d.id} types={types} /></CardContent></Card>
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
