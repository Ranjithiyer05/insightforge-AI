"use client";
import { useState } from "react";
import { CheckCircle2, Droplets, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";
import { Input, Select } from "./ui/input";
import { ErrorNote } from "./ui/misc";

const NUMERIC = ["numeric", "continuous", "integer", "currency", "percentage", "count", "categorical_numeric"];
const METHODS: Record<string, string> = { median: "Fill with median", mean: "Fill with mean", mode: "Fill with most common value", constant: "Fill with a value…", drop: "Drop these rows" };

export function MissingValues({ dataset, onCleaned }: { dataset: any; onCleaned: (d: any) => void }) {
  const cols = dataset.profile.columns.filter((c: any) => c.missing > 0);
  const [choice, setChoice] = useState<Record<string, { method: string; value?: string }>>({});
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isNum = (c: any) => NUMERIC.includes(c.semantic_type);
  const get = (c: any) => choice[c.name] || { method: "" };
  const selected = cols.filter((c: any) => get(c).method);
  const ops = selected.map((c: any) => {
    const ch = get(c);
    return ch.method === "drop" ? { op: "drop_missing_rows", column: c.name } : { op: "fill_missing", column: c.name, method: ch.method, value: ch.value };
  });
  const apply = async () => {
    setBusy(true); setErr(null);
    try { onCleaned(await api(`/datasets/${dataset.id}/clean`, { method: "POST", json: { operations: ops, confirm: true } })); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  if (!cols.length) return <div className="flex items-center gap-2 rounded-xl bg-success-soft p-4 text-[13.5px] text-success"><CheckCircle2 className="size-4" /> This dataset has no missing values.</div>;
  return (
    <div className="space-y-4">
      <p className="text-[13px] text-fg-2">Choose how to treat each column with gaps. Nothing changes until you confirm, and the result is saved as a <span className="font-medium text-fg">new cleaned copy</span>; the original stays untouched. Leaving a column unset is fine: each analysis then handles gaps itself and reports how.</p>
      <div className="overflow-hidden rounded-xl border border-border">
        {cols.map((c: any, i: number) => {
          const ch = get(c);
          return (
            <div key={c.name} className={`grid items-center gap-3 px-4 py-3 sm:grid-cols-[1.3fr_1fr_1.4fr] ${i ? "border-t border-border" : ""}`}>
              <div className="min-w-0">
                <div className="truncate text-[13.5px] font-medium text-fg">{c.name}</div>
                <div className="text-[11.5px] text-fg-3">{c.semantic_type.replace("_", " ")}</div>
              </div>
              <div>
                <div className="flex items-baseline justify-between text-[12px]"><span className="num font-medium text-fg">{c.missing.toLocaleString()}</span><span className="num text-fg-3">{(c.missing_pct * 100).toFixed(1)}%</span></div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3"><div className={`h-full rounded-full ${c.missing_pct > 0.3 ? "bg-warning" : "bg-info"}`} style={{ width: `${Math.max(2, c.missing_pct * 100)}%` }} /></div>
              </div>
              <div className="flex gap-2">
                <Select value={ch.method} onChange={(e) => setChoice({ ...choice, [c.name]: { method: e.target.value } })} aria-label={`Handling for ${c.name}`}>
                  <option value="">Leave as is</option>
                  {Object.entries(METHODS).filter(([m]) => isNum(c) || !["median", "mean"].includes(m)).map(([m, l]) => <option key={m} value={m}>{l}</option>)}
                </Select>
                {ch.method === "constant" && <Input className="w-28" placeholder="value" value={ch.value || ""} onChange={(e) => setChoice({ ...choice, [c.name]: { ...ch, value: e.target.value } })} />}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between gap-3">
        <span className="text-[12.5px] text-fg-3">{selected.length} column(s) selected</span>
        <Button onClick={() => setConfirm(true)} disabled={!selected.length}><Wand2 /> Review and apply</Button>
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent title="Create a cleaned copy?" description="These operations run on a copy. You can always go back to the original dataset.">
          <ul className="space-y-1.5 text-[13px]">{selected.map((c: any) => <li key={c.name} className="flex items-center gap-2"><Droplets className="size-3.5 text-info" /><span className="font-medium text-fg">{c.name}</span><span className="text-fg-3">→ {METHODS[get(c).method]}{get(c).method === "constant" ? ` "${get(c).value ?? ""}"` : ""} ({c.missing.toLocaleString()} cells)</span></li>)}</ul>
          {err && <div className="mt-3"><ErrorNote message={err} /></div>}
          <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button><Button onClick={apply} disabled={busy}>{busy ? "Applying…" : "Create cleaned copy"}</Button></div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
