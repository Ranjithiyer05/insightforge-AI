"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Eye, GitBranch, Lightbulb, Plus, Trash2, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtNum, humanize, timeAgo } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Dialog, DialogContent } from "./ui/dialog";
import { Input, Label, Select } from "./ui/input";
import { ErrorNote, Skeleton } from "./ui/misc";
import { DataGrid } from "./data-grid";
import { motion } from "./motion";

type Step = { op: string; column?: string; reason?: string; [k: string]: any };

const PARAMS: Record<string, { key: string; label: string; options?: [string, string][]; placeholder?: string }[]> = {
  rename_column: [{ key: "new_name", label: "New name" }],
  fill_missing: [{ key: "method", label: "Fill with", options: [["median", "Median"], ["mean", "Mean"], ["mode", "Most common value"], ["constant", "A constant"], ["ffill", "Previous row's value"], ["bfill", "Next row's value"]] },
                 { key: "value", label: "Constant (if chosen)" }],
  convert_type: [{ key: "to", label: "Convert to", options: [["numeric", "Number"], ["integer", "Whole number"], ["string", "Text"], ["boolean", "Yes/No"], ["datetime", "Date/time"]] }],
  parse_dates: [{ key: "output_format", label: "Output format", options: [["%Y-%m-%d", "YYYY-MM-DD"], ["%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS"], ["%Y-%m", "YYYY-MM"]] },
                { key: "dayfirst", label: "Ambiguous dates", options: [["", "Month first (03/04 = 4 March)"], ["1", "Day first (03/04 = 3 April)"]] }],
  normalize_text: [{ key: "case", label: "Letter case", options: [["none", "Keep case, trim spaces"], ["lower", "lower case"], ["upper", "UPPER CASE"], ["title", "Title Case"]] }],
  cap_outliers: [{ key: "k", label: "IQR multiplier", placeholder: "1.5" }],
  remove_outliers: [{ key: "k", label: "IQR multiplier", placeholder: "3" }],
  replace_value: [{ key: "old", label: "Replace this value" }, { key: "new", label: "With (empty = missing)" }],
};

function describe(s: Step, ops: any) {
  const base = ops?.[s.op]?.label || humanize(s.op);
  const extra = PARAMS[s.op]?.map((p) => s[p.key] !== undefined && s[p.key] !== "" ? `${p.label.toLowerCase()}: ${p.options?.find((o) => o[0] === String(s[p.key]))?.[1] ?? s[p.key]}` : null).filter(Boolean).join(", ");
  return `${base}${s.column ? ` · ${s.column}` : ""}${extra ? ` (${extra})` : ""}`;
}

function StepEditor({ columns, ops, onAdd }: { columns: string[]; ops: any; onAdd: (s: Step) => void }) {
  const [op, setOp] = useState("fill_missing");
  const [column, setColumn] = useState(columns[0] || "");
  const [vals, setVals] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const needsCol = ops?.[op]?.needs_column;
  const add = () => {
    const s: Step = { op, reason: reason.trim() || undefined };
    if (needsCol) s.column = column;
    for (const p of PARAMS[op] || []) {
      const v = vals[p.key] ?? p.options?.[0]?.[0] ?? "";
      if (v === "") continue;
      s[p.key] = p.key === "k" ? Number(v) : p.key === "dayfirst" ? v === "1" : v;
    }
    onAdd(s); setVals({}); setReason("");
  };
  return (
    <div className="grid gap-3 rounded-xl border border-border bg-surface-2/40 p-4 md:grid-cols-2">
      <div className="space-y-1.5"><Label htmlFor="op">Operation</Label>
        <Select id="op" value={op} onChange={(e) => { setOp(e.target.value); setVals({}); }}>
          {Object.entries(ops || {}).map(([k, v]: any) => <option key={k} value={k}>{v.label}</option>)}
        </Select></div>
      {needsCol && <div className="space-y-1.5"><Label htmlFor="col">Column</Label>
        <Select id="col" value={column} onChange={(e) => setColumn(e.target.value)}>{columns.map((c) => <option key={c}>{c}</option>)}</Select></div>}
      {(PARAMS[op] || []).map((p) => (
        <div key={p.key} className="space-y-1.5"><Label htmlFor={p.key}>{p.label}</Label>
          {p.options ? <Select id={p.key} value={vals[p.key] ?? p.options[0][0]} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })}>{p.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
            : <Input id={p.key} value={vals[p.key] ?? ""} placeholder={p.placeholder} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })} />}
        </div>
      ))}
      <div className="space-y-1.5 md:col-span-2"><Label htmlFor="reason">Reason (recorded in the cleaning history)</Label>
        <Input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. prices were exported as text with currency symbols" /></div>
      <div className="md:col-span-2"><Button size="sm" onClick={add}><Plus /> Add step</Button></div>
    </div>
  );
}

function StatDelta({ before, after }: { before: any; after: any }) {
  if (!before && !after) return null;
  const keys = ["dtype", "missing", "unique", "mean", "median", "min", "max"].filter((k) => (before && k in before) || (after && k in after));
  return (
    <table className="mt-2 w-full text-[12px]">
      <thead className="text-fg-3"><tr><th className="text-left font-normal">Statistic</th><th className="text-right font-normal">Before</th><th className="text-right font-normal">After</th></tr></thead>
      <tbody>{keys.map((k) => {
        const b = before?.[k], a = after?.[k];
        const changed = String(b) !== String(a);
        return <tr key={k} className={changed ? "text-fg" : "text-fg-3"}><td>{k}</td><td className="text-right num">{typeof b === "number" ? fmtNum(b) : b ?? "—"}</td><td className="text-right num">{typeof a === "number" ? fmtNum(a) : a ?? "—"}</td></tr>;
      })}</tbody>
    </table>
  );
}

function StepResult({ e }: { e: any }) {
  const effects = [
    e.rows_removed ? `${e.rows_removed.toLocaleString()} rows removed` : null,
    e.values_changed !== undefined ? `${e.values_changed.toLocaleString()} values changed` : null,
    e.cells_filled !== undefined ? `${e.cells_filled.toLocaleString()} cells filled (${e.method}${e.value !== undefined && typeof e.value !== "string" ? ` = ${fmtNum(e.value)}` : e.method === "constant" ? ` = ${e.value}` : ""})` : null,
    e.values_capped !== undefined ? `${e.values_capped.toLocaleString()} values capped to [${fmtNum(e.lower)}, ${fmtNum(e.upper)}]` : null,
    e.values_not_convertible !== undefined ? `${e.values_not_convertible.toLocaleString()} values could not be converted` : null,
    e.op === "rename_column" ? `renamed to ${e.to}` : null,
    e.op === "drop_column" ? `${(e.cells_removed ?? 0).toLocaleString()} non-empty cells removed with the column` : null,
  ].filter(Boolean);
  return (
    <div className="rounded-lg border border-border p-3 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2"><Badge tone="accent">Step {e.step}</Badge><span className="font-medium text-fg">{e.label}{e.column ? ` · ${e.column}` : ""}</span>
        <span className="ml-auto num text-fg-3">{e.rows_before.toLocaleString()} → {e.rows_after.toLocaleString()} rows</span></div>
      <div className="mt-1 text-fg-2">{effects.join(" · ") || "No values changed."}</div>
      {e.reason && <div className="mt-1 text-fg-3">Reason: {e.reason}</div>}
      {e.warnings?.map((w: string) => <div key={w} className="mt-1 text-warning">{w}</div>)}
      {e.mapping && Object.keys(e.mapping).length > 0 && <div className="mt-1 text-fg-3">Mapping: {Object.entries(e.mapping).slice(0, 8).map(([a, b]) => `${a} → ${b}`).join("; ")}</div>}
      <StatDelta before={e.before} after={e.after} />
    </div>
  );
}

export function CleaningWorkspace({ dataset, onCleaned }: { dataset: any; onCleaned: (d: any) => void }) {
  const { data: meta } = useApi<any>(`/datasets/${dataset.id}/clean/suggestions`);
  const { data: lin } = useApi<any>(`/datasets/${dataset.id}/lineage`);
  const [steps, setSteps] = useState<Step[]>([]);
  const [preview, setPreview] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const columns = useMemo(() => dataset.profile.columns.map((c: any) => c.name), [dataset]);
  const ops = meta?.operations;

  const change = (s: Step[]) => { setSteps(s); setPreview(null); };
  const move = (i: number, d: number) => { const s = [...steps]; [s[i], s[i + d]] = [s[i + d], s[i]]; change(s); };
  const runPreview = async () => {
    setBusy(true); setErr(null);
    try { setPreview(await api(`/datasets/${dataset.id}/clean/preview`, { method: "POST", json: { operations: steps } })); }
    catch (e: any) { setErr(e.message); setPreview(null); } finally { setBusy(false); }
  };
  const apply = async () => {
    setBusy(true); setErr(null);
    try { const nd = await api(`/datasets/${dataset.id}/clean`, { method: "POST", json: { operations: steps, confirm: true } }); setConfirm(false); onCleaned(nd); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const cmp = preview?.comparison;

  return (
    <div className="grid gap-5 xl:grid-cols-5">
      <div className="space-y-5 xl:col-span-3">
        <Card>
          <CardHeader><div><CardTitle>Cleaning steps</CardTitle><CardDescription>Build a recipe, preview exactly what changes, then save it as a new version. The current version is never modified.</CardDescription></div></CardHeader>
          <CardContent className="space-y-4">
            {meta?.suggestions?.length > 0 && (
              <div className="rounded-xl border border-accent/25 bg-accent-soft/40 p-3">
                <div className="mb-2 flex items-center gap-1.5 text-[12.5px] font-medium text-accent-text"><Lightbulb className="size-4" /> Suggested from the quality check</div>
                <ul className="space-y-1.5">{meta.suggestions.map((s: Step, i: number) => (
                  <li key={i} className="flex items-start gap-2 text-[12.5px]"><span className="flex-1 text-fg-2"><span className="font-medium text-fg">{describe(s, ops)}</span> · {s.reason}</span>
                    <Button size="sm" variant="secondary" onClick={() => change([...steps, s])} disabled={steps.some((x) => JSON.stringify(x) === JSON.stringify(s))}><Plus /> Add</Button></li>
                ))}</ul>
              </div>
            )}
            {ops ? <StepEditor columns={columns} ops={ops} onAdd={(s) => change([...steps, s])} /> : <Skeleton className="h-40" />}
            {steps.length > 0 && (
              <ol className="space-y-1.5">
                {steps.map((s, i) => (
                  <motion.li layout key={i + s.op + (s.column || "")} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[13px]">
                    <span className="flex size-5 items-center justify-center rounded-full bg-surface-3 text-[11px] num">{i + 1}</span>
                    <span className="flex-1 text-fg">{describe(s, ops)}{s.reason && <span className="text-fg-3"> · {s.reason}</span>}</span>
                    <Button size="icon-sm" variant="ghost" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move step up"><ArrowUp /></Button>
                    <Button size="icon-sm" variant="ghost" onClick={() => move(i, 1)} disabled={i === steps.length - 1} aria-label="Move step down"><ArrowDown /></Button>
                    <Button size="icon-sm" variant="ghost" onClick={() => change(steps.filter((_, j) => j !== i))} aria-label="Remove step"><Trash2 /></Button>
                  </motion.li>
                ))}
              </ol>
            )}
            {err && <ErrorNote message={err} />}
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={runPreview} disabled={!steps.length || busy}><Eye /> {busy && !confirm ? "Previewing…" : "Preview changes"}</Button>
              <Button onClick={() => setConfirm(true)} disabled={!preview || busy}><Wand2 /> Save as new version</Button>
            </div>
          </CardContent>
        </Card>

        {preview && (
          <Card>
            <CardHeader><div><CardTitle>Preview: {preview.rows_before.toLocaleString()} → {preview.rows_after.toLocaleString()} rows, {preview.columns_before.length} → {preview.columns_after.length} columns</CardTitle>
              <CardDescription>{cmp.aligned ? `${cmp.changed_rows.toLocaleString()} rows have at least one changed value. The first ${cmp.original.length} are shown side by side.` : cmp.note}</CardDescription></div></CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">{preview.log.map((e: any) => <StepResult key={e.step} e={e} />)}</div>
              {cmp.original.length > 0 && <div className="grid gap-3 lg:grid-cols-2">
                <div><div className="mb-1 text-[12px] font-medium text-fg-3">Original</div><DataGrid columns={preview.columns_before} rows={cmp.original} maxHeight={320} dense /></div>
                <div><div className="mb-1 text-[12px] font-medium text-fg-3">Cleaned</div><DataGrid columns={preview.columns_after} rows={cmp.cleaned} maxHeight={320} dense /></div>
              </div>}
            </CardContent>
          </Card>
        )}
      </div>

      <Card className="h-fit xl:col-span-2">
        <CardHeader><div><CardTitle className="flex items-center gap-1.5"><GitBranch className="size-4" /> Versions and history</CardTitle><CardDescription>Every version stays available; open an earlier one to restore it.</CardDescription></div></CardHeader>
        <CardContent className="space-y-4">
          {!lin ? <Skeleton className="h-24" /> : <>
            <ol className="space-y-1.5">
              {lin.chain.map((v: any, i: number) => (
                <li key={v.id} className="flex items-center gap-2 text-[13px]">
                  <span className="flex size-5 items-center justify-center rounded-full bg-accent-soft text-[10.5px] font-semibold text-accent-text">{i + 1}</span>
                  {v.id === dataset.id ? <span className="font-medium text-fg">{v.name} (this version)</span> : <Link className="text-accent-text hover:underline" href={`/datasets/${v.id}?tab=clean`}>{v.name}</Link>}
                  <span className="ml-auto text-[11.5px] text-fg-3 num">{v.n_rows.toLocaleString()} × {v.n_cols}</span>
                </li>
              ))}
            </ol>
            {lin.children.length > 0 && <div className="text-[12.5px] text-fg-3">Later versions: {lin.children.map((c: any, i: number) => <span key={c.id}>{i ? ", " : ""}<Link className="text-accent-text hover:underline" href={`/datasets/${c.id}?tab=clean`}>{c.name}</Link></span>)}</div>}
            {lin.history.length ? (
              <div className="space-y-3">
                {lin.history.map((h: any, i: number) => (
                  <div key={i} className="rounded-lg border border-border p-3 text-[12.5px]">
                    <div className="flex justify-between text-fg-3"><span>From {h.from_name || h.from_dataset}</span><span>{timeAgo(h.at)}</span></div>
                    {h.rows_before !== undefined && <div className="mt-0.5 num text-fg-3">{h.rows_before.toLocaleString()} → {h.rows_after.toLocaleString()} rows</div>}
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-fg-2">{h.operations.map((o: any, j: number) => (
                      <li key={j}>{o.label || humanize(o.op)}{o.column ? ` · ${o.column}` : ""}{o.rows_removed ? ` · ${o.rows_removed} rows removed` : ""}{o.values_changed !== undefined ? ` · ${o.values_changed} values changed` : ""}{o.cells_filled !== undefined ? ` · ${o.cells_filled} cells filled` : ""}{o.reason ? <span className="text-fg-3"> · {o.reason}</span> : null}</li>
                    ))}</ul>
                  </div>
                ))}
              </div>
            ) : <p className="text-[12.5px] text-fg-3">This is an original upload; no cleaning has been applied.</p>}
          </>}
        </CardContent>
      </Card>

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent title="Save cleaned version?" description="A new dataset version is created from these steps. The current version stays exactly as it is.">
          {preview && <div className="space-y-3 text-[13px]">
            <ul className="list-disc space-y-1 pl-5 text-fg-2">{preview.log.map((e: any) => <li key={e.step}>{e.label}{e.column ? ` · ${e.column}` : ""}</li>)}</ul>
            <p className="text-fg-3">Result: {preview.rows_after.toLocaleString()} rows × {preview.columns_after.length} columns.</p>
            {err && <ErrorNote message={err} />}
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button><Button onClick={apply} disabled={busy}>{busy ? "Saving…" : "Save new version"}</Button></div>
          </div>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
