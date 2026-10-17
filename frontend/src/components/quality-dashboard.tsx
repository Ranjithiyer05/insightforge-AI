"use client";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { cn, fmtNum, humanize } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input, Select } from "./ui/input";
import { AnimatedNumber, Stagger, StaggerItem } from "./motion";

const tip = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };
const TYPE_GROUP: Record<string, string> = {
  numeric: "Numerical", integer: "Numerical", categorical: "Categorical", categorical_numeric: "Categorical", boolean: "Categorical",
  datetime: "Date/time", identifier: "Identifier", text: "Text", empty: "Empty",
};

function Tile({ label, value, format, hint, tone }: { label: string; value: number; format?: (n: number) => string; hint?: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="text-[12px] text-fg-3">{label}</div>
      <div className={cn("mt-1 text-[24px] font-semibold tracking-tight num", tone)}><AnimatedNumber value={value} format={format} /></div>
      {hint && <div className="mt-1 text-[11.5px] text-fg-3">{hint}</div>}
    </div>
  );
}

/** Interactive data-quality dashboard built from the stored profile. */
export function QualityDashboard({ dataset }: { dataset: any }) {
  const p = dataset.profile;
  const [sev, setSev] = useState("all");
  const [kind, setKind] = useState("all");
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  const typeCounts = useMemo(() => {
    const m: Record<string, number> = {};
    p.columns.forEach((c: any) => { const g = TYPE_GROUP[c.semantic_type] || "Other"; m[g] = (m[g] || 0) + 1; });
    return Object.entries(m).map(([type, count]) => ({ type, count }));
  }, [p]);
  const missing = useMemo(() => p.columns.filter((c: any) => c.missing > 0).map((c: any) => ({ column: c.name, pct: +(c.missing_pct * 100).toFixed(2), missing: c.missing }))
    .sort((a: any, b: any) => b.pct - a.pct).slice(0, 20), [p]);
  const kinds = Array.from(new Set(p.issues.map((i: any) => i.kind))) as string[];
  const issues = p.issues.filter((i: any) => (sev === "all" || i.severity === sev) && (kind === "all" || i.kind === kind) &&
    (!q || (i.column || "").toLowerCase().includes(q.toLowerCase()) || i.message.toLowerCase().includes(q.toLowerCase())));
  const cols = p.columns.filter((c: any) => !typeFilter || (TYPE_GROUP[c.semantic_type] || "Other") === typeFilter);
  const outlierCols = p.columns.filter((c: any) => c.outliers_iqr > 0).length;

  return (
    <div className="space-y-5">
      <Stagger className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StaggerItem><Tile label="Quality score" value={Math.round((p.quality_score ?? 0) * 100)} format={(n) => `${Math.round(n)}/100`} hint="Heuristic: missing, duplicates, warnings" /></StaggerItem>
        <StaggerItem><Tile label="Rows" value={p.n_rows} /></StaggerItem>
        <StaggerItem><Tile label="Columns" value={p.n_cols} /></StaggerItem>
        <StaggerItem><Tile label="Missing cells" value={(p.missing_pct ?? 0) * 100} format={(n) => `${n.toFixed(1)}%`} hint={`${(p.missing_cells ?? 0).toLocaleString()} cells`} /></StaggerItem>
        <StaggerItem><Tile label="Duplicate rows" value={p.duplicates} tone={p.duplicates ? "text-warning" : undefined} /></StaggerItem>
        <StaggerItem><Tile label="Columns with outliers" value={outlierCols} hint="Outside 1.5×IQR; not necessarily errors" /></StaggerItem>
      </Stagger>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><div><CardTitle>Column types</CardTitle><CardDescription>Click a bar to filter the column list below.</CardDescription></div>
            {typeFilter && <button className="text-[12px] text-accent-text hover:underline" onClick={() => setTypeFilter(null)}>Clear filter</button>}</CardHeader>
          <CardContent><div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={typeCounts} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis dataKey="type" tickLine={false} axisLine={false} fontSize={11} interval={0} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={11} width={28} />
                <Tooltip contentStyle={tip} cursor={{ fill: "var(--surface-2)" }} />
                <Bar dataKey="count" name="Columns" radius={[4, 4, 0, 0]} onClick={(d: any) => setTypeFilter(d.type === typeFilter ? null : d.type)} className="cursor-pointer">
                  {typeCounts.map((t) => <Cell key={t.type} fill={!typeFilter || typeFilter === t.type ? "var(--chart-1)" : "var(--surface-3)"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div></CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Missing values by column</CardTitle><CardDescription>{missing.length ? "Percentage of rows with no value." : "No missing values."}</CardDescription></div></CardHeader>
          <CardContent>{missing.length ? <div style={{ height: Math.max(140, missing.length * 26 + 30) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={missing} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                <XAxis type="number" unit="%" tickLine={false} axisLine={false} fontSize={11} />
                <YAxis type="category" dataKey="column" width={120} tickLine={false} axisLine={false} fontSize={11} interval={0} />
                <Tooltip contentStyle={tip} formatter={(v: any, _n: any, it: any) => [`${v}% (${it.payload.missing.toLocaleString()} rows)`, "Missing"]} cursor={{ fill: "var(--surface-2)" }} />
                <Bar dataKey="pct" fill="var(--chart-3)" radius={[0, 4, 4, 0]} maxBarSize={16} />
              </BarChart>
            </ResponsiveContainer>
          </div> : <p className="py-10 text-center text-[13px] text-fg-3">Every column is complete.</p>}</CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><div><CardTitle>Quality warnings</CardTitle><CardDescription>{issues.length} of {p.issues.length} shown. Unusual values are flagged for review, not treated as errors.</CardDescription></div></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-3">
            <Select value={sev} onChange={(e) => setSev(e.target.value)} aria-label="Filter by severity"><option value="all">All severities</option><option value="warning">Warnings</option><option value="info">Information</option></Select>
            <Select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by type"><option value="all">All issue types</option>{kinds.map((k) => <option key={k} value={k}>{humanize(k)}</option>)}</Select>
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search column or message" aria-label="Search issues" />
          </div>
          <ul className="space-y-1.5">
            {issues.length === 0 && <li className="py-4 text-center text-[13px] text-fg-3">No issues match these filters.</li>}
            {issues.map((i: any, k: number) => (
              <li key={k} className={cn("flex items-start gap-2.5 rounded-lg border px-3 py-2 text-[13px]", i.severity === "warning" ? "border-warning/30 bg-warning-soft/40" : "border-border")}>
                {i.kind === "possible_leakage" ? <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" /> : i.severity === "warning" ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" /> : <Info className="mt-0.5 size-4 shrink-0 text-fg-3" />}
                <span className="flex-1 text-fg">{i.message}</span>
                <Badge tone="outline">{humanize(i.kind)}</Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><div><CardTitle>Columns{typeFilter ? `: ${typeFilter}` : ""}</CardTitle><CardDescription>Types are inferred from names and values; review them before relying on them.</CardDescription></div></CardHeader>
        <CardContent>
          <div className="overflow-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-[12.5px]">
              <thead className="bg-surface-2 text-left text-fg-2"><tr>{["Column", "Type", "Missing", "Unique", "Mean / mode", "Median", "Std", "Range", "Outliers"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {cols.map((c: any) => (
                  <tr key={c.name} className="border-t border-border">
                    <td className="px-3 py-1.5 font-medium text-fg">{c.name}</td>
                    <td className="px-3 py-1.5"><Badge tone="outline">{humanize(c.semantic_type)}</Badge></td>
                    <td className="px-3 py-1.5 num text-fg-2">{c.missing ? `${c.missing.toLocaleString()} (${(c.missing_pct * 100).toFixed(1)}%)` : "0"}</td>
                    <td className="px-3 py-1.5 num text-fg-2">{c.unique.toLocaleString()}</td>
                    <td className="px-3 py-1.5 num text-fg-2">{c.stats?.mean !== undefined ? fmtNum(c.stats.mean) : c.mode ?? "—"}</td>
                    <td className="px-3 py-1.5 num text-fg-2">{c.stats?.median !== undefined ? fmtNum(c.stats.median) : "—"}</td>
                    <td className="px-3 py-1.5 num text-fg-2">{c.stats?.std !== undefined ? fmtNum(c.stats.std) : "—"}</td>
                    <td className="px-3 py-1.5 num text-fg-3">{c.stats?.min !== undefined && c.stats?.min !== null ? `${typeof c.stats.min === "number" ? fmtNum(c.stats.min) : c.stats.min} – ${typeof c.stats.max === "number" ? fmtNum(c.stats.max) : c.stats.max}` : "—"}</td>
                    <td className="px-3 py-1.5 num text-fg-2">{c.outliers_iqr ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
