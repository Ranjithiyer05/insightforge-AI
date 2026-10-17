"use client";
import { useState } from "react";
import { Activity, BarChart3, ChevronDown, GitCompareArrows, Layers, Percent, Sigma, TrendingUp, TriangleAlert } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { cn, fmtNum } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Select } from "./ui/input";
import { ErrorNote, Skeleton } from "./ui/misc";
import { ChartRenderer } from "./charts/chart-renderer";
import { DataGrid } from "./data-grid";
import { AnimatedNumber, Stagger, StaggerItem, motion } from "./motion";

const KIND_ICON: Record<string, any> = { trend: TrendingUp, change: Activity, group_difference: GitCompareArrows, correlation: Layers, concentration: Percent,
  distribution: BarChart3, missing: TriangleAlert, imbalance: Sigma };

function heat(v: number | null) {
  if (v == null) return "transparent";
  const a = Math.min(1, Math.abs(v));
  return v >= 0 ? `color-mix(in oklab, var(--chart-1) ${8 + a * 80}%, transparent)` : `color-mix(in oklab, var(--chart-4) ${8 + a * 80}%, transparent)`;
}

function Insight({ ins }: { ins: any }) {
  const [open, setOpen] = useState(false);
  const Icon = KIND_ICON[ins.kind] || Activity;
  const ev = ins.evidence || {};
  return (
    <Card className="lift p-4">
      <div className="flex items-start gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text"><Icon className="size-4" /></div>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold text-fg">{ins.title}</div>
          <p className="mt-1 text-[13px] leading-relaxed text-fg-2">{ins.detail}</p>
          <p className="mt-1.5 text-[12px] text-fg-3">{ins.caveat}</p>
          <button onClick={() => setOpen(!open)} className="mt-2 inline-flex items-center gap-1 text-[12px] text-accent-text hover:underline" aria-expanded={open}>
            Evidence <ChevronDown className={cn("size-3.5 transition", open && "rotate-180")} />
          </button>
          {open && (
            <motion.dl initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded-lg bg-surface-2 p-2.5 text-[12px]">
              <dt className="text-fg-3">Method</dt><dd className="text-fg">{ev.method}</dd>
              {ev.n !== undefined && <><dt className="text-fg-3">Sample size</dt><dd className="num text-fg">{ev.n.toLocaleString()}</dd></>}
              {ev.statistic !== undefined && <><dt className="text-fg-3">Statistic</dt><dd className="num text-fg">{fmtNum(ev.statistic)}</dd></>}
              {ev.p_value !== undefined && <><dt className="text-fg-3">p-value</dt><dd className="num text-fg">{ev.p_value < 0.001 ? "< 0.001" : fmtNum(ev.p_value)}</dd></>}
              {ev.q_value !== undefined && <><dt className="text-fg-3">Adjusted q</dt><dd className="num text-fg">{ev.q_value < 0.001 ? "< 0.001" : fmtNum(ev.q_value)}</dd></>}
              {ev.effect_size !== undefined && <><dt className="text-fg-3">Effect size</dt><dd className="num text-fg">{fmtNum(ev.effect_size)}</dd></>}
              {ev.values && <><dt className="text-fg-3">Values</dt><dd className="text-fg">{Object.entries(ev.values).map(([k, v]) => `${k}: ${typeof v === "number" ? fmtNum(v) : v}`).join(" · ")}</dd></>}
            </motion.dl>
          )}
        </div>
        <Badge tone="outline" className="shrink-0">{ins.kind.replace("_", " ")}</Badge>
      </div>
    </Card>
  );
}

export function EdaView({ datasetId }: { datasetId: string }) {
  const { data, error, loading } = useApi<any>(`/datasets/${datasetId}/eda`);
  const [hist, setHist] = useState<string | null>(null);
  const [cat, setCat] = useState<string | null>(null);
  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <div className="space-y-4"><div className="grid grid-cols-2 gap-3 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)}</div><Skeleton className="h-64" /><Skeleton className="h-64" /></div>;

  const histCol = hist || Object.keys(data.histograms)[0];
  const catSum = data.categorical.find((c: any) => c.column === cat) || data.categorical[0];
  const t = data.trend;
  return (
    <div className="space-y-5">
      <Stagger className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {data.kpis.map((k: any) => (
          <StaggerItem key={k.key}>
            <div className="h-full rounded-xl border border-border bg-surface p-4" title={k.formula}>
              <div className="text-[12px] text-fg-3">{k.label}</div>
              <div className="mt-1 text-[22px] font-semibold tracking-tight num text-fg">
                {k.format === "text" ? <span className="text-[13.5px] leading-snug">{k.value}</span> :
                  <AnimatedNumber value={k.value} format={(n) => k.format === "pct" ? `${(n * 100).toFixed(1)}%` : k.format === "int" ? Math.round(n).toLocaleString() : fmtNum(n)} />}
              </div>
              {k.formula && <div className="mt-0.5 font-mono text-[10.5px] text-fg-3">{k.formula}</div>}
            </div>
          </StaggerItem>
        ))}
      </Stagger>

      <section>
        <div className="mb-3 flex items-end justify-between"><div><h2 className="text-[16px] font-semibold text-fg">Automatically discovered insights</h2>
          <p className="text-[12.5px] text-fg-3">Ranked by strength of evidence. Each is computed from the data; open “Evidence” for the test and sample size.</p></div></div>
        {data.insights.length ? <Stagger className="grid gap-3 lg:grid-cols-2">{data.insights.map((i: any) => <StaggerItem key={i.id}><Insight ins={i} /></StaggerItem>)}</Stagger>
          : <Card className="p-6 text-center text-[13px] text-fg-3">No pattern passed the evidence thresholds. That is a result too: the data shows no strong trends, group differences or correlations.</Card>}
      </section>

      {t && (
        <ChartRenderer spec={{ id: "trend", kind: "line", title: `${t.aggregation === "sum" ? "Total" : "Count of"} ${t.measure} per ${t.granularity}${t.last_period_partial ? " (last period looks incomplete)" : ""}`,
          data: t.series, x: "period", series: [{ key: "value", label: t.measure }] }} height={260} />
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {histCol && <Card><CardHeader><div><CardTitle>Distribution</CardTitle><CardDescription>Histogram of a numeric column.</CardDescription></div>
          <Select className="w-44" value={histCol} onChange={(e) => setHist(e.target.value)} aria-label="Column">{Object.keys(data.histograms).map((c) => <option key={c}>{c}</option>)}</Select></CardHeader>
          <CardContent><ChartRenderer spec={{ id: "hist", kind: "bar", title: `Distribution of ${histCol}`, data: data.histograms[histCol], x: "bin", series: [{ key: "count", label: "Rows" }] }} height={220} /></CardContent></Card>}
        {catSum && <Card><CardHeader><div><CardTitle>Category ranking</CardTitle><CardDescription>{catSum.by_measure ? `Ranked by total ${catSum.by_measure.measure}.` : "Ranked by row count."}</CardDescription></div>
          <Select className="w-44" value={catSum.column} onChange={(e) => setCat(e.target.value)} aria-label="Category column">{data.categorical.map((c: any) => <option key={c.column}>{c.column}</option>)}</Select></CardHeader>
          <CardContent>{catSum.by_measure ?
            <ChartRenderer spec={{ id: "rank", kind: "bar", title: `Total ${catSum.by_measure.measure} by ${catSum.column}`, data: catSum.by_measure.rows, x: "value", series: [{ key: "sum", label: `Total ${catSum.by_measure.measure}` }], layout: "horizontal" }} height={220} /> :
            <ChartRenderer spec={{ id: "rank", kind: "bar", title: `Rows by ${catSum.column}`, data: catSum.top, x: "value", series: [{ key: "count", label: "Rows" }], layout: "horizontal" }} height={220} />}</CardContent></Card>}
      </div>

      {data.correlations && (
        <Card><CardHeader><div><CardTitle>Correlation matrix</CardTitle><CardDescription>{data.correlations.method}. {data.correlations.note}</CardDescription></div></CardHeader>
          <CardContent className="overflow-x-auto scrollbar-thin">
            <table className="text-[11.5px]"><thead><tr><th />{data.correlations.columns.map((c: string) => <th key={c} className="max-w-[90px] truncate px-1 pb-1 text-left font-medium text-fg-3" title={c}>{c}</th>)}</tr></thead>
              <tbody>{data.correlations.matrix.map((row: any[], i: number) => (
                <tr key={i}><th className="max-w-[140px] truncate pr-2 text-right font-medium text-fg-3" title={data.correlations.columns[i]}>{data.correlations.columns[i]}</th>
                  {row.map((v, j) => <td key={j} title={`${data.correlations.columns[i]} × ${data.correlations.columns[j]}: ${v ?? "n/a"}`} className="size-11 border border-surface text-center num text-fg" style={{ background: heat(v) }}>{v == null ? "" : v.toFixed(2)}</td>)}</tr>
              ))}</tbody></table>
          </CardContent></Card>
      )}

      {data.group_tests.length > 0 && (
        <Card><CardHeader><div><CardTitle>Grouped summaries: {data.measure} by category</CardTitle><CardDescription>Kruskal-Wallis tests whether the distribution differs between groups; q is adjusted for the number of tests.</CardDescription></div></CardHeader>
          <CardContent><DataGrid columns={["group", "groups", "n", "highest", "lowest", "statistic", "q", "effect_size_epsilon2"]} dense maxHeight={320}
            rows={data.group_tests.map((g: any) => ({ ...g, highest: `${g.highest.group} (${fmtNum(g.highest.mean)})`, lowest: `${g.lowest.group} (${fmtNum(g.lowest.mean)})` }))} /></CardContent></Card>
      )}

      <Card><CardHeader><div><CardTitle>Summary statistics</CardTitle><CardDescription>{data.notes.join(" ")}</CardDescription></div></CardHeader>
        <CardContent><DataGrid columns={["column", "count", "missing", "mean", "median", "mode", "std", "variance", "min", "q1", "q3", "max", "skew", "kurtosis", "outliers_iqr"]} rows={data.summary} dense maxHeight={360} /></CardContent></Card>
    </div>
  );
}
