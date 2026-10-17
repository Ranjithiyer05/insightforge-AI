"use client";
import { useMemo, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, Hash, Type } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { cn, fmtNum } from "@/lib/utils";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { ErrorNote, Skeleton, Tabs } from "./ui/misc";

function heat(v: number | null) {
  if (v == null) return "transparent";
  const a = Math.min(1, Math.abs(v));
  return v >= 0 ? `rgba(240, 86, 29, ${0.08 + a * 0.82})` : `rgba(13, 148, 136, ${0.08 + a * 0.82})`;
}

function ColumnCard({ c }: { c: any }) {
  const data = c.kind === "numeric" ? c.histogram : c.top;
  return (
    <Card className="lift p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0"><div className="truncate text-[13.5px] font-semibold text-fg">{c.name}</div>
          <div className="text-[11.5px] text-fg-3">{(c.semantic_type || c.kind).replace("_", " ")}{c.missing ? ` · ${c.missing.toLocaleString()} missing` : ""}</div></div>
        <div className={cn("flex size-7 shrink-0 items-center justify-center rounded-lg", c.kind === "numeric" ? "bg-accent-soft text-accent-text" : "bg-info-soft text-info")}>{c.kind === "numeric" ? <Hash className="size-3.5" /> : <Type className="size-3.5" />}</div>
      </div>
      {c.semantic_type === "identifier" ? (
        <div className="flex h-32 items-center justify-center rounded-xl bg-surface-2 text-center text-[12.5px] text-fg-3">Identifier column<br />{c.unique?.toLocaleString()} distinct values, not charted</div>
      ) : <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          {c.kind === "numeric" ? (
            <BarChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }} barCategoryGap={1}>
              <XAxis dataKey="bin" hide /><YAxis hide />
              <Tooltip cursor={{ fill: "var(--surface-2)" }} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="count" fill="var(--chart-1)" radius={[3, 3, 0, 0]} />
            </BarChart>
          ) : (
            <BarChart data={data.slice(0, 6)} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
              <XAxis type="number" hide /><YAxis type="category" dataKey="value" width={88} tickLine={false} axisLine={false} fontSize={11} interval={0} />
              <Tooltip cursor={{ fill: "var(--surface-2)" }} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="count" fill="var(--chart-2)" radius={[0, 3, 3, 0]} maxBarSize={14} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>}
      {c.kind === "numeric" && c.stats && (
        <div className="mt-2 grid grid-cols-4 gap-1 text-center text-[11px]">
          {[["min", c.stats.min], ["median", c.stats.median], ["mean", c.stats.mean], ["max", c.stats.max]].map(([l, v]) => (
            <div key={l as string} className="rounded-md bg-surface-2 py-1"><div className="text-fg-3">{l}</div><div className="num font-medium text-fg">{fmtNum(v as number)}</div></div>
          ))}
        </div>
      )}
      {c.kind === "categorical" && <div className="mt-2 text-[11.5px] text-fg-3">{c.unique.toLocaleString()} distinct values{c.other ? ` · ${c.other.toLocaleString()} rows outside the top 12` : ""}</div>}
      {c.kind === "numeric" && Math.abs(c.stats?.skew ?? 0) > 1 && <Badge tone="warning" className="mt-2">Skewed (skew {fmtNum(c.stats.skew)})</Badge>}
    </Card>
  );
}

export function DatasetExplorer({ id }: { id: string }) {
  const { data, error } = useApi<any>(`/datasets/${id}/explore`);
  const [view, setView] = useState<"dist" | "corr">("dist");
  const [filter, setFilter] = useState<"all" | "numeric" | "categorical">("all");
  const cols = useMemo(() => (data?.columns || []).filter((c: any) => filter === "all" || c.kind === filter), [data, filter]);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <div className="grid gap-4 md:grid-cols-3">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-56" />)}</div>;
  const corr = data.correlation;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs value={view} onChange={setView} items={[{ value: "dist", label: "Distributions", count: data.columns.length }, { value: "corr", label: "Correlations" }]} />
        {view === "dist" && <Tabs value={filter} onChange={setFilter} items={[{ value: "all", label: "All" }, { value: "numeric", label: "Numeric" }, { value: "categorical", label: "Categorical" }]} />}
      </div>
      {view === "dist" ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{cols.map((c: any) => <ColumnCard key={c.name} c={c} />)}</div>
      ) : !corr ? (
        <Card className="p-8 text-center text-[13px] text-fg-3"><BarChart3 className="mx-auto mb-2 size-6" />At least two numeric columns are needed for a correlation matrix.</Card>
      ) : (
        <Card className="p-5">
          <div className="overflow-auto">
            <table className="border-separate border-spacing-1 text-[11.5px]">
              <thead><tr><th />{corr.columns.map((c: string) => <th key={c} className="h-28 w-12 align-bottom font-medium text-fg-2"><div className="w-12 -rotate-45 origin-bottom-left translate-x-4 whitespace-nowrap text-left">{c}</div></th>)}</tr></thead>
              <tbody>{corr.matrix.map((row: (number | null)[], i: number) => (
                <tr key={i}><th className="whitespace-nowrap pr-2 text-right font-medium text-fg-2">{corr.columns[i]}</th>
                  {row.map((v, j) => <td key={j} title={`${corr.columns[i]} × ${corr.columns[j]}: ${v ?? "n/a"}`} className={cn("size-12 rounded-md text-center num", v != null && Math.abs(v) > 0.55 ? "text-white" : "text-fg-2")} style={{ background: heat(v) }}>{v == null ? "—" : v.toFixed(2)}</td>)}
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-4 text-[12px] text-fg-3">
            <span className="flex items-center gap-1.5"><span className="size-3 rounded" style={{ background: heat(-0.9) }} /> negative</span>
            <span className="flex items-center gap-1.5"><span className="size-3 rounded" style={{ background: heat(0.9) }} /> positive</span>
            <span>{corr.note}</span>
          </div>
        </Card>
      )}
    </div>
  );
}
