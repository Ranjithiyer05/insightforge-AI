"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { BarChart3, Brain, Database, Download, FileUp, LayoutGrid, MessageSquare, Workflow } from "lucide-react";
import { api, download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { ErrorNote, Skeleton } from "./ui/misc";

const ICON: Record<string, any> = { dataset: Database, question: MessageSquare, model: Brain, analysis: BarChart3, dashboard: LayoutGrid };
const LINK: Record<string, (id: string) => string> = { dataset: (id) => `/datasets/${id}?tab=pipeline`, analysis: (id) => `/analyses/${id}`, dashboard: (id) => `/dashboards/${id}` };

export function PipelineView({ dataset, onNewVersion }: { dataset: any; onNewVersion: (d: any) => void }) {
  const { data, error, loading } = useApi<any>(`/datasets/${dataset.id}/pipeline`);
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function upload(f: File) {
    setBusy(true); setErr(null);
    const fd = new FormData();
    fd.append("file", f);
    try { onNewVersion(await api(`/datasets/${dataset.id}/versions`, { method: "POST", body: fd })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <Skeleton className="h-80" />;
  const versions = data.nodes.filter((n: any) => n.type === "dataset");
  const children = (id: string) => data.edges.filter((e: any) => e.from === id).map((e: any) => data.nodes.find((n: any) => n.id === e.to)).filter((n: any) => n && n.type !== "dataset");
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader><div><CardTitle className="flex items-center gap-2"><Workflow className="size-4" /> Data pipeline</CardTitle>
          <CardDescription>Every version of this dataset, how it was produced, and what was built on it. Dashboards always use the latest version.</CardDescription></div>
          <div className="flex gap-2">
            <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,.xlsx,.xls" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            <Button variant="secondary" size="sm" onClick={() => fileRef.current?.click()} disabled={busy}><FileUp /> {busy ? "Uploading…" : "Upload newer data"}</Button>
            <Button variant="secondary" size="sm" onClick={() => download(`/datasets/${dataset.id}/reproduce.zip`)}><Download /> Reproduce (.zip)</Button>
          </div></CardHeader>
        <CardContent>
          {err && <ErrorNote message={err} />}
          <ol className="relative space-y-4 border-l border-border pl-6">
            {versions.map((v: any) => {
              const kids = children(v.id);
              return (
                <li key={v.id} className="relative">
                  <span className={cn("absolute -left-[31px] top-1 flex size-4 items-center justify-center rounded-full border-2 bg-surface", v.current ? "border-accent" : "border-border")} />
                  <div className={cn("rounded-xl border p-3", v.current ? "border-accent bg-accent-soft/30" : "border-border")}>
                    <div className="flex flex-wrap items-center gap-2">
                      <Link href={LINK.dataset(v.id)} className="text-[13.5px] font-medium text-fg hover:text-accent-text">{v.label}</Link>
                      <Badge tone="outline">{v.kind === "upload" ? "original upload" : v.kind === "cleaned" ? "cleaned" : "newer data"}</Badge>
                      {v.id === data.latest && <Badge tone="accent">latest</Badge>}
                      <span className="num text-[12px] text-fg-3">{v.rows.toLocaleString()} rows × {v.cols} · {timeAgo(v.created_at)} · {v.sha256}</span>
                    </div>
                    {v.steps.length > 0 && <ol className="mt-2 flex flex-wrap gap-1.5">{v.steps.map((s: string, i: number) => <li key={i} className="rounded-md bg-surface-2 px-2 py-0.5 text-[11.5px] text-fg-2">{i + 1}. {s}</li>)}</ol>}
                    {kids.length > 0 && (
                      <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
                        {kids.map((k: any) => {
                          const I = ICON[k.type];
                          const inner = <><I className="size-3.5 shrink-0 text-fg-3" /><span className="truncate">{k.label}</span>{k.detail && <span className="ml-auto shrink-0 text-fg-3">{k.detail.slice(0, 40)}</span>}</>;
                          return <li key={k.id} className="flex items-center gap-2 rounded-lg border border-border px-2 py-1.5 text-[12px] text-fg-2">
                            {LINK[k.type] ? <Link href={LINK[k.type](k.id)} className="flex min-w-0 flex-1 items-center gap-2 hover:text-fg">{inner}</Link> : inner}</li>;
                        })}
                      </ul>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          <p className="mt-4 text-[12px] text-fg-3">The reproduce bundle contains the exact cleaning code, the recorded steps with their reasons, and your saved questions as pandas scripts. Your data is not included.</p>
        </CardContent>
      </Card>
    </div>
  );
}
