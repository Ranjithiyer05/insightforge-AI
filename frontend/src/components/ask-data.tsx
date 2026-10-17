"use client";
import { useState } from "react";
import { ArrowUp, Code2, Info, Pin, PinOff, RotateCcw, Sparkles, Trash2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input, Select } from "./ui/input";
import { ErrorNote, Skeleton, Tabs } from "./ui/misc";
import { ChartRenderer } from "./charts/chart-renderer";
import { CodeViewer } from "./code-viewer";
import { DataGrid } from "./data-grid";
import { motion } from "./motion";

const AGGS = [["sum", "Total"], ["mean", "Average"], ["median", "Median"], ["min", "Minimum"], ["max", "Maximum"], ["count", "Count"], ["nunique", "Distinct count"]];
const GRAINS = ["day", "week", "month", "quarter", "year"];

/** Editable interpretation: the user can correct what the parser chose, and the answer is recomputed from the edited spec. */
function SpecEditor({ spec, schema, onRun, busy }: { spec: any; schema: any; onRun: (s: any) => void; busy: boolean }) {
  const [s, setS] = useState<any>(spec);
  const set = (k: string, v: any) => setS({ ...s, [k]: v === "" ? null : v });
  if (!["aggregate", "trend"].includes(s.op)) return null;
  return (
    <div className="grid gap-2 rounded-lg border border-border bg-surface-2/50 p-3 sm:grid-cols-2 lg:grid-cols-3">
      <label className="text-[11.5px] text-fg-3">Calculation
        <Select value={s.agg || "count"} onChange={(e) => set("agg", e.target.value)} className="mt-1">{AGGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></label>
      <label className="text-[11.5px] text-fg-3">Of column
        <Select value={s.measure || ""} onChange={(e) => set("measure", e.target.value)} className="mt-1"><option value="">(rows)</option>
          {(s.agg === "nunique" || s.agg === "count" ? schema.columns : schema.numeric).map((c: string) => <option key={c}>{c}</option>)}</Select></label>
      <label className="text-[11.5px] text-fg-3">Grouped by
        <Select value={s.group_by || ""} onChange={(e) => set("group_by", e.target.value)} className="mt-1"><option value="">(no grouping)</option>
          {schema.categorical.map((c: string) => <option key={c}>{c}</option>)}</Select></label>
      <label className="text-[11.5px] text-fg-3">Over time
        <Select value={s.op === "trend" ? s.grain : ""} disabled={!schema.dates.length} className="mt-1"
          onChange={(e) => setS({ ...s, op: e.target.value ? "trend" : "aggregate", grain: e.target.value || null, date_col: e.target.value ? (s.date_col || schema.dates[0]) : null })}>
          <option value="">(not over time)</option>{GRAINS.map((g) => <option key={g} value={g}>per {g}</option>)}</Select></label>
      <div className="flex items-end gap-2">
        <label className="flex-1 text-[11.5px] text-fg-3">Show
          <Select value={s.limit ? `${s.sort}:${s.limit}` : ""} className="mt-1" disabled={s.op === "trend" || !s.group_by}
            onChange={(e) => { const [so, l] = e.target.value.split(":"); setS({ ...s, sort: so || "desc", limit: l ? +l : null }); }}>
            <option value="">All groups</option>{[1, 5, 10].map((n) => <option key={`d${n}`} value={`desc:${n}`}>Top {n}</option>)}{[1, 5, 10].map((n) => <option key={`a${n}`} value={`asc:${n}`}>Bottom {n}</option>)}</Select></label>
        <Button size="sm" onClick={() => onRun({ ...s, measure: s.agg === "count" && !s.measure ? null : s.measure })} disabled={busy}><RotateCcw /> Recompute</Button>
      </div>
    </div>
  );
}

function AddToDashboard({ a, datasetId }: { a: any; datasetId: string }) {
  const boards = useApi<any[]>("/dashboards");
  const [msg, setMsg] = useState<string | null>(null);
  const scalar = a.rows.length === 1 && a.columns.length === 1;
  async function add(id: string) {
    let bid = id;
    try {
      if (id === "new") bid = (await api("/dashboards", { method: "POST", json: { name: "My dashboard", dataset_id: datasetId } })).id;
      await api(`/dashboards/${bid}/tiles`, { method: "POST", json: { kind: scalar ? "kpi" : "ask", title: a.question || a.interpretation, question: a.question, spec: a.spec } });
      setMsg(bid);
    } catch (e: any) { setMsg(`error:${e.message}`); }
  }
  if (msg && !msg.startsWith("error:")) return <a href={`/dashboards/${msg}`} className="text-[12px] text-accent-text hover:underline">Added. Open dashboard</a>;
  return (
    <span className="flex items-center gap-1.5">
      <Select className="h-8 w-48 text-[12px]" value="" onChange={(e) => e.target.value && add(e.target.value)} aria-label="Add to dashboard">
        <option value="">Add to dashboard…</option>
        {boards.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        <option value="new">New dashboard</option>
      </Select>
      {msg?.startsWith("error:") && <span className="text-[12px] text-danger">{msg.slice(6)}</span>}
    </span>
  );
}

function Answer({ a, schema, onRun, busy, datasetId }: { a: any; schema: any; onRun: (s: any) => void; busy: boolean; datasetId: string }) {
  const [view, setView] = useState<"chart" | "table" | "code">(a.chart ? "chart" : "table");
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Card>
        <CardHeader className="items-start">
          <div className="min-w-0">
            <CardDescription className="mb-1">{a.question}</CardDescription>
            <CardTitle className="text-[17px] leading-snug">{a.headline}</CardTitle>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
              <Badge tone="outline">Computed: {a.interpretation}</Badge>
              <span className="num">{a.rows_used.toLocaleString()} of {a.rows_total.toLocaleString()} rows used</span>
              {a.parser === "llm" && <Badge tone="outline"><Sparkles className="size-3" /> Interpreted by the language model</Badge>}
              <span className="ml-auto"><AddToDashboard a={a} datasetId={datasetId} /></span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {(a.assumptions.length > 0 || a.warnings.length > 0) && (
            <ul className="space-y-1 text-[12.5px]">
              {a.assumptions.map((t: string) => <li key={t} className="flex gap-2 text-fg-2"><Info className="mt-0.5 size-3.5 shrink-0 text-fg-3" />{t}</li>)}
              {a.warnings.map((t: string) => <li key={t} className="flex gap-2 text-fg-2"><TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />{t}</li>)}
            </ul>
          )}
          <SpecEditor key={JSON.stringify(a.spec)} spec={a.spec} schema={schema} onRun={onRun} busy={busy} />
          <Tabs value={view} onChange={setView} items={[...(a.chart ? [{ value: "chart" as const, label: "Chart" }] : []), { value: "table" as const, label: `Table (${a.rows.length})` }, { value: "code" as const, label: "Code" }]} />
          {view === "chart" && a.chart && <ChartRenderer spec={a.chart} height={300} />}
          {view === "table" && <DataGrid columns={a.columns} rows={a.rows} dense maxHeight={360} />}
          {view === "code" && <div className="space-y-3">
            <div><div className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-fg-2"><Code2 className="size-3.5" /> pandas (this exact code produced the answer)</div><CodeViewer code={a.code} filename="answer.py" maxHeight={260} /></div>
            {a.sql && <div><div className="mb-1 text-[12px] font-medium text-fg-2">Equivalent SQL (for reference, table named <code>data</code>)</div><CodeViewer code={a.sql} filename="answer.sql" maxHeight={200} /></div>}
          </div>}
          {a.truncated && <p className="text-[12px] text-fg-3">Showing the first 500 result rows.</p>}
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function AskData({ datasetId }: { datasetId: string }) {
  const meta = useApi<any>(`/datasets/${datasetId}/ask/suggestions`);
  const hist = useApi<any[]>(`/datasets/${datasetId}/ask/history`);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [answers, setAnswers] = useState<any[]>([]);

  async function run(body: { question?: string; spec?: any }) {
    setBusy(true); setErr(null);
    try {
      const a = await api(`/datasets/${datasetId}/ask`, { method: "POST", json: body });
      setAnswers((xs) => [a, ...xs].slice(0, 10));
      if (body.question) setQ("");
      hist.reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  const ask = (text: string) => text.trim() && run({ question: text.trim() });

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_280px]">
      <div className="space-y-4">
        <Card className="p-4">
          <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex gap-2">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about this data, e.g. “total revenue by region”" aria-label="Question" maxLength={500} autoFocus />
            <Button type="submit" disabled={busy || !q.trim()} aria-label="Ask"><ArrowUp /></Button>
          </form>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {meta.data?.suggestions.map((s: string) => (
              <button key={s} onClick={() => ask(s)} disabled={busy} className="rounded-full border border-border px-2.5 py-1 text-[12px] text-fg-2 transition hover:border-accent hover:text-fg disabled:opacity-50">{s}</button>
            ))}
          </div>
          <p className="mt-3 text-[11.5px] text-fg-3">Answers are computed with pandas on the stored file; the code is shown with every answer. {meta.data?.llm ? "A language model only helps interpret questions the rules cannot parse." : "No language model is used."} Supported: totals, averages, counts, grouping, top/bottom N, filters, trends, correlations, distributions, unique values and matching rows.</p>
        </Card>
        {err && <ErrorNote message={err} />}
        {busy && <Skeleton className="h-40" />}
        {answers.map((a) => <Answer key={a.id} a={a} schema={a.schema} onRun={(spec) => run({ spec })} busy={busy} datasetId={datasetId} />)}
        {!answers.length && !busy && <Card className="p-8 text-center text-[13px] text-fg-3">Ask a question or pick a suggestion. Each answer shows how it was computed, so you can check and correct it.</Card>}
      </div>
      <Card className="h-fit">
        <CardHeader><div><CardTitle>Saved questions</CardTitle><CardDescription>Your recent questions on this dataset.</CardDescription></div></CardHeader>
        <CardContent className="space-y-1">
          {hist.loading && <Skeleton className="h-24" />}
          {hist.data?.length === 0 && <p className="text-[12.5px] text-fg-3">None yet.</p>}
          {hist.data?.map((h) => (
            <div key={h.id} className="group flex items-start gap-1 rounded-lg px-2 py-1.5 hover:bg-surface-2">
              <button className="min-w-0 flex-1 text-left" onClick={() => run({ question: h.question, spec: h.spec })} disabled={busy} title="Run again on the current data">
                <div className={cn("truncate text-[12.5px] text-fg", h.pinned && "font-medium")}>{h.question}</div>
                <div className="truncate text-[11px] text-fg-3">{timeAgo(h.created_at)} · {h.headline}</div>
              </button>
              <button aria-label={h.pinned ? "Unpin" : "Pin"} className="p-1 text-fg-3 opacity-60 hover:text-fg group-hover:opacity-100" onClick={async () => { await api(`/ask/${h.id}/pin?pinned=${!h.pinned}`, { method: "POST" }); hist.reload(); }}>
                {h.pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}</button>
              <button aria-label="Delete" className="p-1 text-fg-3 opacity-60 hover:text-danger group-hover:opacity-100" onClick={async () => { await api(`/ask/${h.id}`, { method: "DELETE" }); hist.reload(); }}><Trash2 className="size-3.5" /></button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
