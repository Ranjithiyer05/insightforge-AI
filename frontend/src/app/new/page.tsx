"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, CheckCircle2, Database, FileSpreadsheet, Lightbulb, ShoppingCart, UploadCloud, Users, Wand2 } from "lucide-react";
import { api, uploadWithProgress } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, fmtBytes } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Textarea } from "@/components/ui/input";
import { ErrorNote, PageHeader, Progress, Skeleton } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";
import { DataGrid } from "@/components/data-grid";
import { ColumnTable, QualitySummary } from "@/components/dataset-profile";
import { useWorkspace } from "@/components/workspace";
import { DEMO_QUESTION } from "@/lib/demo";


function suggestions(profile: any): string[] {
  const r = profile.roles || {};
  const out: string[] = [];
  const cls = profile.candidate_targets?.find((t: any) => t.task === "classification" && t.score >= 0.8);
  const num = profile.numeric_columns?.[0];
  const cat = profile.categorical_columns?.find((c: string) => !(r.id || []).includes(c));
  if (r.date && (r.revenue || r.profit) && r.cost) out.push(DEMO_QUESTION);
  if (r.date && (r.revenue || num)) out.push(`Forecast ${(r.revenue || [num])[0]} for the next 3 months`);
  if (cls) out.push(`Which records are likely to have ${cls.column} = yes? Predict ${cls.column}.`);
  if (cls && num && num !== cls.column) out.push(`Is there a significant difference in ${num} between ${cls.column} groups?`);
  if (cat && (r.revenue || num)) out.push(`Compare ${(r.revenue || [num])[0]} by ${cat}`);
  if ((profile.numeric_columns || []).length >= 2) out.push("Segment the records into natural groups");
  out.push("Give me an overview of this dataset");
  return Array.from(new Set(out)).slice(0, 6);
}

function Dropzone({ onFile, disabled, maxMb }: { onFile: (f: File) => void; disabled?: boolean; maxMb: number }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) onFile(f); }}
      onClick={() => !disabled && input.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
      className={cn("flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition",
        over ? "border-accent bg-accent-soft/50" : "border-border-strong hover:border-accent/50 hover:bg-surface-2/50", disabled && "pointer-events-none opacity-60")}>
      <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-accent-soft text-accent-text"><UploadCloud className="size-5" /></div>
      <p className="text-sm font-medium text-fg">Drop a CSV or Excel file here, or click to browse</p>
      <p className="mt-1 text-[12.5px] text-fg-3">.csv, .xlsx or .xlsm · up to {maxMb} MB · treated as untrusted input and kept private to your account</p>
      <input ref={input} type="file" accept=".csv,.xlsx,.xlsm" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
    </div>
  );
}

function NewAnalysis() {
  const sp = useSearchParams();
  const router = useRouter();
  const { current, setCurrent } = useWorkspace();
  const [dataset, setDataset] = useState<any | null>(null);
  const [preview, setPreview] = useState<any | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [fileInfo, setFileInfo] = useState<{ name: string; size: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [question, setQuestion] = useState(sp.get("q") || "");
  const [planning, setPlanning] = useState(false);
  const { data: library } = useApi<any[]>("/datasets");
  const { data: status } = useApi<any>("/status");
  const MAX_MB: number = status?.limits?.max_upload_mb ?? 20; // the server's limit, so large files fail before uploading

  const loadDataset = useCallback(async (id: string) => {
    const [d, p] = await Promise.all([api(`/datasets/${id}`), api(`/datasets/${id}/preview?limit=50`)]);
    setDataset(d); setPreview(p);
    setCurrent({ datasetId: d.id, datasetName: d.name });
  }, [setCurrent]);

  useEffect(() => { const id = sp.get("dataset"); if (id) loadDataset(id).catch((e) => setErr(e.message)); }, [sp]); // eslint-disable-line

  const onFile = async (f: File) => {
    setErr(null);
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!["csv", "xlsx", "xlsm"].includes(ext || "")) return setErr("Unsupported file type. Upload a .csv, .xlsx or .xlsm file.");
    if (f.size > MAX_MB * 1024 * 1024) return setErr(`The file is ${fmtBytes(f.size)}, above the ${MAX_MB} MB limit.`);
    setFileInfo({ name: f.name, size: f.size });
    setProgress(0);
    try {
      const d = await uploadWithProgress(f, current.projectId || null, setProgress);
      await loadDataset(d.id);
    } catch (e: any) { setErr(e.message); } finally { setProgress(null); }
  };
  const demo = async (which: "retail" | "churn") => {
    setErr(null); setProgress(100); setFileInfo({ name: which === "retail" ? "retail_sales_SYNTHETIC.csv" : "customer_churn_SYNTHETIC.csv", size: 0 });
    try {
      const d = await api(`/datasets/demo/${which}${current.projectId ? `?project_id=${current.projectId}` : ""}`, { method: "POST" });
      await loadDataset(d.id);
      if (!question) setQuestion(which === "retail" ? DEMO_QUESTION : "Which customers are likely to churn?");
    } catch (e: any) { setErr(e.message); } finally { setProgress(null); }
  };
  const plan = async () => {
    setPlanning(true); setErr(null);
    try {
      const a = await api("/analyses/plan", { method: "POST", json: { dataset_id: dataset.id, question, project_id: current.projectId || null } });
      router.push(`/analyses/${a.id}`);
    } catch (e: any) { setErr(e.message); setPlanning(false); }
  };
  const sugg = useMemo(() => (dataset ? suggestions(dataset.profile) : []), [dataset]);
  const types = useMemo(() => Object.fromEntries((dataset?.profile.columns || []).map((c: any) => [c.name, c.semantic_type.replace("_", " ")])), [dataset]);

  return (
    <div className="space-y-6 animate-in">
      <PageHeader title="New analysis" description="Upload data, review its quality, ask a question, then approve the plan before anything runs." />
      <ol className="flex flex-wrap items-center gap-2 text-[12.5px]">
        {["Choose data", "Review profile", "Ask a question", "Approve plan"].map((s, i) => {
          const done = (i === 0 && dataset) || (i === 1 && dataset && question);
          const active = (i === 0 && !dataset) || (i === 1 && dataset && !question) || (i === 2 && dataset && question);
          return <li key={s} className="flex items-center gap-2">
            <span className={cn("flex size-5 items-center justify-center rounded-full text-[11px] font-semibold", done ? "bg-success text-white" : active ? "bg-accent text-white" : "bg-surface-3 text-fg-3")}>{done ? <CheckCircle2 className="size-3.5" /> : i + 1}</span>
            <span className={active ? "font-medium text-fg" : "text-fg-3"}>{s}</span>{i < 3 && <span className="mx-1 h-px w-6 bg-border-strong" />}
          </li>;
        })}
      </ol>
      {err && <ErrorNote message={err} />}

      {!dataset && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader><div><CardTitle>Upload a dataset</CardTitle><CardDescription>Files are validated, parsed safely (no formulas or macros run) and stored under a random id.</CardDescription></div></CardHeader>
            <CardContent className="space-y-3">
              <Dropzone onFile={onFile} disabled={progress !== null} maxMb={MAX_MB} />
              {progress !== null && fileInfo && (
                <div className="rounded-lg border border-border p-3">
                  <div className="mb-2 flex items-center justify-between text-[13px]"><span className="flex items-center gap-2"><FileSpreadsheet className="size-4 text-fg-3" />{fileInfo.name}</span><span className="num text-fg-3">{progress < 100 ? `${progress}%` : "Profiling…"}</span></div>
                  <Progress value={progress} />
                </div>
              )}
            </CardContent>
          </Card>
          <div className="space-y-4">
            <Card>
              <CardHeader><div><CardTitle>Demo datasets</CardTitle><CardDescription>Explicitly synthetic records with known, planted effects.</CardDescription></div></CardHeader>
              <CardContent className="space-y-2">
                <Button variant="secondary" className="w-full justify-start" onClick={() => demo("retail")}><ShoppingCart /> Retail sales (synthetic)</Button>
                <Button variant="secondary" className="w-full justify-start" onClick={() => demo("churn")}><Users /> Customer churn (synthetic)</Button>
              </CardContent>
            </Card>
            {library && library.length > 0 && (
              <Card>
                <CardHeader><div><CardTitle>Use an existing dataset</CardTitle></div></CardHeader>
                <CardContent><Select defaultValue="" onChange={(e) => e.target.value && loadDataset(e.target.value)}>
                  <option value="" disabled>Select from your library…</option>
                  {library.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.n_rows.toLocaleString()} rows)</option>)}
                </Select></CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {dataset && (
        <>
          <Card>
            <CardHeader>
              <div><CardTitle className="flex items-center gap-2"><Database className="size-4 text-fg-3" />{dataset.name}{dataset.is_synthetic && <Badge tone="warning">Synthetic demo data</Badge>}</CardTitle>
                <CardDescription>{dataset.n_rows.toLocaleString()} rows · {dataset.n_cols} columns · {fmtBytes(dataset.size_bytes)} · quality score {(dataset.quality_score * 100).toFixed(0)}/100</CardDescription></div>
              <Button variant="ghost" size="sm" onClick={() => { setDataset(null); setPreview(null); }}>Change data</Button>
            </CardHeader>
            <CardContent className="grid gap-5 xl:grid-cols-5">
              <div className="xl:col-span-3 space-y-2">
                <div className="text-[12.5px] font-medium text-fg-2">Preview (first 50 rows)</div>
                {preview ? <DataGrid columns={preview.columns} rows={preview.rows} types={types} maxHeight={340} dense /> : <Skeleton className="h-64" />}
              </div>
              <div className="xl:col-span-2 space-y-2">
                <div className="text-[12.5px] font-medium text-fg-2">Data-quality summary</div>
                <QualitySummary dataset={dataset} onCleaned={(nd) => loadDataset(nd.id)} />
              </div>
            </CardContent>
          </Card>
          <details className="group rounded-xl border border-border bg-surface"><summary className="cursor-pointer px-5 py-3 text-[13.5px] font-medium text-fg">Column details</summary><div className="px-5 pb-5"><ColumnTable profile={dataset.profile} /></div></details>

          <Card>
            <CardHeader><div><CardTitle>What do you want to know?</CardTitle><CardDescription>Ask in plain English. The agent turns it into an explicit, editable plan.</CardDescription></div></CardHeader>
            <CardContent className="space-y-3">
              <Textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Why did profit decline last month, and which products should we investigate first?"
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && question.trim().length > 3) plan(); }} />
              <div className="flex flex-wrap gap-1.5">
                <span className="flex items-center gap-1 text-[12px] text-fg-3"><Lightbulb className="size-3.5" /> Suggested for this dataset:</span>
                {sugg.map((s) => <button key={s} onClick={() => setQuestion(s)} className="rounded-full border border-border px-2.5 py-1 text-[12px] text-fg-2 hover:border-accent/40 hover:bg-accent-soft/50 hover:text-fg">{s}</button>)}
              </div>
              <div className="flex justify-end"><Button onClick={plan} disabled={planning || question.trim().length < 4}><Wand2 /> {planning ? "Planning…" : "Generate analysis plan"} <ArrowRight /></Button></div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense><NewAnalysis /></Suspense>;
}
