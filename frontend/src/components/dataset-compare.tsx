"use client";
import { useState } from "react";
import { ArrowLeftRight, Columns2 } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { cn, fmtNum } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Label, Select } from "./ui/input";
import { EmptyState, ErrorNote, Skeleton } from "./ui/misc";
import { ChartRenderer } from "./charts/chart-renderer";

const TONE: Record<string, string> = { "large shift": "text-danger", "moderate shift": "text-warning", stable: "text-fg-3" };

function ColumnRow({ c, a, b }: { c: any; a: string; b: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="cursor-pointer border-t border-border hover:bg-surface-2" onClick={() => setOpen(!open)} aria-expanded={open}>
        <td className="px-3 py-2 font-medium text-fg">{c.column}</td>
        <td className="px-3 py-2 text-fg-2">{c.kind}</td>
        <td className={cn("px-3 py-2 font-medium", TONE[c.verdict] || "text-fg-3")}>{c.verdict || c.note || "—"}</td>
        <td className="px-3 py-2 num text-fg-2">{c.kind === "numeric" ? `${fmtNum(c.mean_a)} → ${fmtNum(c.mean_b)}${c.change_pct != null ? ` (${c.change_pct > 0 ? "+" : ""}${c.change_pct.toFixed(1)}%)` : ""}` : c.kind === "categorical" ? `${c.new_categories.length} new, ${c.missing_categories.length} gone` : ""}</td>
        <td className="px-3 py-2 num text-fg-2">{c.effect != null ? `${c.effect_label === "PSI" ? "PSI" : "effect"} ${c.effect.toFixed(3)}` : ""}</td>
        <td className="px-3 py-2 num text-fg-3">{c.q_value != null ? (c.q_value < 0.001 ? "< 0.001" : c.q_value.toFixed(3)) : ""}</td>
        <td className="px-3 py-2 num text-fg-3">{`${(c.missing_a * 100).toFixed(1)}% → ${(c.missing_b * 100).toFixed(1)}%`}</td>
      </tr>
      {open && (c.histogram || c.shares) && (
        <tr><td colSpan={7} className="bg-surface-2/40 px-3 py-3">
          {c.histogram && <ChartRenderer spec={{ id: `h-${c.column}`, kind: "bar", title: `Share of rows by ${c.column} (quantile bins of both datasets)`, data: c.histogram, x: "bin", series: [{ key: a, label: a }, { key: b, label: b }] }} height={220} />}
          {c.shares && <ChartRenderer spec={{ id: `s-${c.column}`, kind: "bar", title: `Share of rows by ${c.column} (largest changes)`, data: c.shares, x: "value", series: [{ key: a, label: a }, { key: b, label: b }], layout: "horizontal" }} height={Math.max(180, c.shares.length * 30 + 40)} />}
          {c.new_categories?.length > 0 && <p className="mt-2 text-[12px] text-fg-2">New in {b}: {c.new_categories.join(", ")}</p>}
          {c.missing_categories?.length > 0 && <p className="text-[12px] text-fg-2">Gone from {b}: {c.missing_categories.join(", ")}</p>}
        </td></tr>
      )}
    </>
  );
}

export function DatasetCompare() {
  const { data: list } = useApi<any[]>("/datasets");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const { data, error, loading } = useApi<any>(a && b && a !== b ? `/compare/datasets?a=${a}&b=${b}` : null);
  return (
    <div className="space-y-5">
      <Card className="p-4">
        <div className="grid items-end gap-3 md:grid-cols-[1fr_auto_1fr]">
          <div className="space-y-1.5"><Label>Dataset A (reference)</Label><Select value={a} onChange={(e) => setA(e.target.value)}><option value="">Select…</option>{(list || []).map((d) => <option key={d.id} value={d.id}>{d.name} · {d.n_rows.toLocaleString()} rows</option>)}</Select></div>
          <Button variant="ghost" size="icon" aria-label="Swap" onClick={() => { setA(b); setB(a); }}><ArrowLeftRight /></Button>
          <div className="space-y-1.5"><Label>Dataset B (compared)</Label><Select value={b} onChange={(e) => setB(e.target.value)}><option value="">Select…</option>{(list || []).filter((d) => d.id !== a).map((d) => <option key={d.id} value={d.id}>{d.name} · {d.n_rows.toLocaleString()} rows</option>)}</Select></div>
        </div>
        <p className="mt-2 text-[12px] text-fg-3">Useful for two months of the same export, or a dataset and its cleaned version.</p>
      </Card>
      {!a || !b ? <EmptyState icon={Columns2} title="Pick two datasets" description="See added or removed columns, type changes, and which columns' distributions shifted." /> :
        error ? <ErrorNote message={error} /> : loading || !data ? <Skeleton className="h-80" /> : (
          <>
            <Card>
              <CardHeader><div><CardTitle>Summary</CardTitle><CardDescription>{data.method}</CardDescription></div></CardHeader>
              <CardContent className="space-y-2 text-[13.5px] text-fg">
                {data.summary.map((s: string) => <p key={s}>{s}</p>)}
                <div className="flex flex-wrap gap-1.5">
                  {data.added_columns.map((c: string) => <Badge key={`+${c}`} tone="outline" className="text-success">+ {c}</Badge>)}
                  {data.removed_columns.map((c: string) => <Badge key={`-${c}`} tone="outline" className="text-danger">− {c}</Badge>)}
                  {data.type_changes.map((t: any) => <Badge key={`t${t.column}`} tone="outline">{t.column}: {t.a} → {t.b}</Badge>)}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><div><CardTitle>Shared columns</CardTitle><CardDescription>Click a row to see the distributions side by side. With large samples, tiny shifts are statistically significant, so the verdict also requires a meaningful effect size.</CardDescription></div></CardHeader>
              <CardContent>
                <div className="overflow-auto rounded-lg border border-border scrollbar-thin">
                  <table className="w-full text-[12.5px]">
                    <thead className="bg-surface-2 text-left text-fg-2"><tr>{["Column", "Type", "Verdict", "Change", "Effect size", "Adjusted q", "Missing"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr></thead>
                    <tbody>{data.columns.map((c: any) => <ColumnRow key={c.column} c={c} a={data.a.name} b={data.b.name} />)}</tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </>
        )}
    </div>
  );
}
