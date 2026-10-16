"use client";
import { useState } from "react";
import { AlertTriangle, Info, ShieldAlert, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn, fmtNum, humanize } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";
import { ErrorNote } from "./ui/misc";

const FIX_LABEL: Record<string, string> = {
  drop_duplicates: "Remove duplicate rows", normalize_categories: "Standardise spellings", drop_column: "Drop column", exclude_feature: "Excluded automatically from models",
};

export function QualitySummary({ dataset, onCleaned }: { dataset: any; onCleaned?: (d: any) => void }) {
  const p = dataset.profile;
  const [pending, setPending] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const issues = [...p.issues].sort((a: any, b: any) => (a.severity === "warning" ? -1 : 1) - (b.severity === "warning" ? -1 : 1));
  const apply = async () => {
    setBusy(true); setErr(null);
    try {
      const op = pending.suggested_fix === "drop_duplicates" ? { op: "drop_duplicates" } : { op: pending.suggested_fix, column: pending.column };
      const nd = await api(`/datasets/${dataset.id}/clean`, { method: "POST", json: { operations: [op], confirm: true } });
      setPending(null);
      onCleaned?.(nd);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[["Rows", p.n_rows.toLocaleString()], ["Columns", p.n_cols], ["Missing cells", `${(p.missing_pct * 100).toFixed(1)}%`], ["Duplicate rows", p.duplicates.toLocaleString()]].map(([k, v]) => (
          <div key={k as string} className="rounded-lg border border-border bg-surface-2/50 px-3 py-2"><div className="text-[11.5px] text-fg-3">{k}</div><div className="text-base font-semibold num text-fg">{v}</div></div>
        ))}
      </div>
      {Object.keys(p.roles || {}).length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
          <span className="text-fg-3">Detected fields:</span>
          {Object.entries(p.roles).filter(([r]) => r !== "id").map(([role, cols]: any) => <Badge key={role} tone="accent">{role}: {cols.join(", ")}</Badge>)}
        </div>
      )}
      <ul className="space-y-1.5">
        {issues.length === 0 && <li className="text-[13px] text-fg-3">No data-quality issues detected.</li>}
        {issues.map((i: any, k: number) => (
          <li key={k} className={cn("flex items-start gap-2.5 rounded-lg border px-3 py-2 text-[13px]", i.severity === "warning" ? "border-warning/30 bg-warning-soft/50" : "border-border")}>
            {i.kind === "possible_leakage" ? <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" /> : i.severity === "warning" ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" /> : <Info className="mt-0.5 size-4 shrink-0 text-fg-3" />}
            <div className="flex-1"><span className="text-fg">{i.message}</span> <span className="text-[11.5px] text-fg-3">({humanize(i.kind)})</span></div>
            {i.destructive && i.suggested_fix && onCleaned && <Button size="sm" variant="secondary" onClick={() => setPending(i)}><Wand2 /> {FIX_LABEL[i.suggested_fix] || humanize(i.suggested_fix)}</Button>}
            {i.suggested_fix === "exclude_feature" && <span className="text-[11.5px] text-fg-3">{FIX_LABEL.exclude_feature}</span>}
          </li>
        ))}
      </ul>
      <p className="text-[11.5px] text-fg-3">{p.notes?.[0]}</p>
      <Dialog open={!!pending} onOpenChange={(o) => !o && setPending(null)}>
        <DialogContent title="Review cleaning operation" description="This changes data. InsightForge creates a cleaned copy and keeps the original dataset untouched.">
          {pending && <div className="space-y-3 text-[13px]">
            <div className="rounded-lg border border-border bg-surface-2 p-3"><div className="font-medium">{FIX_LABEL[pending.suggested_fix]}</div><div className="mt-1 text-fg-2">{pending.message}</div></div>
            {err && <ErrorNote message={err} />}
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setPending(null)}>Cancel</Button><Button onClick={apply} disabled={busy}>{busy ? "Applying…" : "Create cleaned copy"}</Button></div>
          </div>}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function ColumnTable({ profile }: { profile: any }) {
  return (
    <div className="overflow-auto rounded-lg border border-border scrollbar-thin">
      <table className="w-full text-[12.5px]">
        <thead className="bg-surface-2 text-left text-fg-2"><tr>{["Column", "Type", "Roles", "Missing", "Unique", "Summary"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>
          {profile.columns.map((c: any) => (
            <tr key={c.name} className="border-t border-border">
              <td className="px-3 py-1.5 font-medium text-fg">{c.name}</td>
              <td className="px-3 py-1.5"><Badge tone="outline">{humanize(c.semantic_type)}</Badge></td>
              <td className="px-3 py-1.5 text-fg-2">{c.roles.join(", ") || "—"}</td>
              <td className="px-3 py-1.5 num text-fg-2">{c.missing ? `${c.missing} (${(c.missing_pct * 100).toFixed(1)}%)` : "0"}</td>
              <td className="px-3 py-1.5 num text-fg-2">{c.unique.toLocaleString()}</td>
              <td className="px-3 py-1.5 text-fg-3">
                {c.stats?.mean !== undefined ? `mean ${fmtNum(c.stats.mean)} · median ${fmtNum(c.stats.median)} · range ${fmtNum(c.stats.min)}–${fmtNum(c.stats.max)}` :
                  c.stats?.min ? `${c.stats.min} → ${c.stats.max}` : c.top_values ? c.top_values.slice(0, 3).map((t: any) => `${t.value} (${t.count})`).join(", ") : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
