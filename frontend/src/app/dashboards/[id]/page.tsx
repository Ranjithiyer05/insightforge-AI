"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowDown, ArrowLeft, ArrowUp, BellRing, CheckCircle2, Code2, Maximize2, Minimize2, Pencil, RefreshCw, StickyNote, Trash2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, fmtNum, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select, Textarea } from "@/components/ui/input";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { ChartRenderer } from "@/components/charts/chart-renderer";
import { CodeViewer } from "@/components/code-viewer";
import { AnimatedNumber, Stagger, StaggerItem } from "@/components/motion";

const RULES = [[">", "above"], [">=", "at or above"], ["<", "below"], ["<=", "at or below"], ["change_pct_below", "drops by more than (%)"], ["change_pct_above", "rises by more than (%)"]];

function RuleEditor({ tile, onSave }: { tile: any; onSave: (rule: any) => void }) {
  const [op, setOp] = useState(tile.rule?.op || "<");
  const [th, setTh] = useState<string>(tile.rule ? String(tile.rule.op === "change_pct_below" ? -tile.rule.threshold : tile.rule.threshold) : "");
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
      <span className="text-fg-3">Alert when value</span>
      <Select className="h-8 w-44" value={op} onChange={(e) => setOp(e.target.value)}>{RULES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
      <Input className="h-8 w-28" type="number" step="any" value={th} onChange={(e) => setTh(e.target.value)} aria-label="Threshold" />
      <Button size="sm" disabled={th === ""} onClick={() => onSave({ op, threshold: op === "change_pct_below" ? -Math.abs(+th) : +th })}>Save rule</Button>
      {tile.rule && <Button size="sm" variant="ghost" onClick={() => onSave(null)}>Remove rule</Button>}
    </div>
  );
}

function Tile({ t, editing, onChange, onMove, onRemove }: { t: any; editing: boolean; onChange: (patch: any) => void; onMove: (d: number) => void; onRemove: () => void }) {
  const [code, setCode] = useState(false);
  const [rule, setRule] = useState(false);
  const r = t.result;
  const m = t.monitor;
  return (
    <Card className={cn("flex h-full flex-col p-4", m?.status === "breach" && "border-warning/50")}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-semibold text-fg">{t.title || t.question || (t.kind === "note" ? "Note" : "Tile")}</div>
          {r && <div className="truncate text-[11.5px] text-fg-3">{r.interpretation}</div>}
        </div>
        {editing ? (
          <div className="flex shrink-0 gap-0.5">
            <Button size="icon" variant="ghost" aria-label="Move up" onClick={() => onMove(-1)}><ArrowUp /></Button>
            <Button size="icon" variant="ghost" aria-label="Move down" onClick={() => onMove(1)}><ArrowDown /></Button>
            <Button size="icon" variant="ghost" aria-label="Toggle width" onClick={() => onChange({ size: t.size === "wide" ? "normal" : "wide" })}>{t.size === "wide" ? <Minimize2 /> : <Maximize2 />}</Button>
            <Button size="icon" variant="ghost" aria-label="Remove tile" onClick={onRemove}><Trash2 /></Button>
          </div>
        ) : r && <button aria-label="Show code" className="p-1 text-fg-3 hover:text-fg" onClick={() => setCode(!code)}><Code2 className="size-4" /></button>}
      </div>
      {editing && t.kind !== "note" && <Input className="mt-2 h-8" value={t.title} placeholder="Tile title" onChange={(e) => onChange({ title: e.target.value })} aria-label="Tile title" />}
      <div className="mt-3 flex-1">
        {t.kind === "note" ? (editing ? <Textarea value={t.text} onChange={(e) => onChange({ text: e.target.value })} rows={4} aria-label="Note text" /> : <p className="whitespace-pre-wrap text-[13px] text-fg-2">{t.text}</p>)
          : t.error ? <ErrorNote message={t.error} />
          : t.kind === "kpi" && t.value != null ? (
            <div>
              <div className="num text-[30px] font-semibold tracking-tight text-fg"><AnimatedNumber value={t.value} format={(n) => fmtNum(n)} /></div>
              {m && <div className={cn("mt-1 flex items-start gap-1.5 text-[12px]", m.status === "breach" ? "text-warning" : "text-fg-3")}>
                {m.status === "breach" ? <BellRing className="mt-0.5 size-3.5 shrink-0" /> : <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success" />}<span>{m.message} Checked {timeAgo(m.evaluated_at)}.</span></div>}
              {m?.history?.length > 1 && <div className="mt-2"><ChartRenderer spec={{ id: `h${t.id}`, kind: "line", title: "Value at each data version", data: m.history.map((h: any, i: number) => ({ version: `v${i + 1}`, value: h.value })), x: "version", series: [{ key: "value", label: "Value" }] }} height={120} /></div>}
            </div>
          ) : r?.chart ? <ChartRenderer spec={r.chart} height={t.size === "wide" ? 260 : 220} />
          : r ? <p className="text-[14px] text-fg">{r.headline}</p> : null}
        {r?.warnings?.length > 0 && !editing && <p className="mt-2 flex gap-1.5 text-[11.5px] text-fg-3"><TriangleAlert className="mt-0.5 size-3 shrink-0" />{r.warnings[0]}</p>}
        {code && r && <div className="mt-2"><CodeViewer code={r.code} maxHeight={200} /></div>}
        {editing && t.kind === "kpi" && (rule ? <RuleEditor tile={t} onSave={(ru) => { onChange({ rule: ru }); setRule(false); }} />
          : <button className="mt-2 text-[12px] text-accent-text hover:underline" onClick={() => setRule(true)}>{t.rule ? "Edit alert rule" : "Add alert rule"}</button>)}
      </div>
    </Card>
  );
}

export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<any>(`/dashboards/${id}`);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<any[] | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <Skeleton className="h-96" />;
  const tiles = draft ?? data.tiles;
  const strip = (ts: any[]) => ts.map(({ result, value, monitor, error: _e, ...rest }) => rest);
  async function save() {
    setErr(null);
    try { await api(`/dashboards/${id}`, { method: "PATCH", json: { tiles: strip(tiles), ...(name ? { name } : {}) } }); setEditing(false); setDraft(null); setName(null); reload(); }
    catch (e: any) { setErr(e.message); }
  }
  const change = (i: number, patch: any) => setDraft(tiles.map((t: any, j: number) => (j === i ? { ...t, ...patch } : t)));
  const move = (i: number, d: number) => { const n = [...tiles]; const j = i + d; if (j < 0 || j >= n.length) return; [n[i], n[j]] = [n[j], n[i]]; setDraft(n); };
  return (
    <div className="space-y-5 animate-in">
      <Link href="/dashboards" className="inline-flex items-center gap-1 text-[13px] text-fg-3 hover:text-fg"><ArrowLeft className="size-3.5" /> Dashboards</Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          {editing ? <Input className="h-10 text-[20px] font-semibold" value={name ?? data.name} onChange={(e) => setName(e.target.value)} aria-label="Dashboard name" /> : <h1 className="text-[26px] font-semibold tracking-tight text-fg">{data.name}</h1>}
          <p className="mt-1 text-[13px] text-fg-3">Showing <Link className="text-accent-text hover:underline" href={`/datasets/${data.dataset.id}`}>{data.dataset.name}</Link> ({data.dataset.n_rows.toLocaleString()} rows){data.versions > 1 ? `, the latest of ${data.versions} versions` : ""}. Every tile is recomputed from the data when this page loads.</p>
        </div>
        <div className="flex gap-2">
          {editing ? <>
            <Button variant="secondary" onClick={() => setDraft([...tiles, { id: undefined, kind: "note", title: "", text: "" }])}><StickyNote /> Add note</Button>
            <Button variant="ghost" onClick={() => { setEditing(false); setDraft(null); setName(null); }}>Cancel</Button>
            <Button onClick={save}>Save</Button>
          </> : <>
            <Button variant="secondary" onClick={reload}><RefreshCw /> Refresh</Button>
            <Button variant="secondary" onClick={() => setEditing(true)}><Pencil /> Edit</Button>
            <Button variant="ghost" aria-label="Delete dashboard" onClick={async () => { if (confirm("Delete this dashboard? The data is not affected.")) { await api(`/dashboards/${id}`, { method: "DELETE" }); router.push("/dashboards"); } }}><Trash2 /></Button>
          </>}
        </div>
      </div>
      {err && <ErrorNote message={err} />}
      {!tiles.length ? <Card className="p-8 text-center text-[13px] text-fg-3">No tiles yet. Open the dataset's <Link className="text-accent-text hover:underline" href={`/datasets/${data.dataset_id}?tab=ask`}>Ask tab</Link>, ask a question, and choose “Add to dashboard”.</Card> : (
        <Stagger className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {tiles.map((t: any, i: number) => (
            <StaggerItem key={t.id || `new${i}`} className={cn(t.size === "wide" && "md:col-span-2")}>
              <Tile t={t} editing={editing} onChange={(p) => change(i, p)} onMove={(d) => move(i, d)} onRemove={() => setDraft(tiles.filter((_: any, j: number) => j !== i))} />
            </StaggerItem>
          ))}
        </Stagger>
      )}
      {editing && <p className="text-[12px] text-fg-3">KPI alert rules are checked each time the dashboard is opened after a new data version arrives; each check is recorded once per version, so alerts are never repeated or invented.</p>}
    </div>
  );
}
