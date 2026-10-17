"use client";
import { useState } from "react";
import { Info, TriangleAlert } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { fmtNum, humanize } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Select } from "./ui/input";
import { ErrorNote, Skeleton, Tabs } from "./ui/misc";
import { ChartRenderer } from "./charts/chart-renderer";
import { DataGrid } from "./data-grid";

const Note = ({ children, warn }: { children: React.ReactNode; warn?: boolean }) => (
  <p className="flex gap-1.5 text-[12.5px] text-fg-2">{warn ? <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" /> : <Info className="mt-0.5 size-3.5 shrink-0 text-fg-3" />}<span>{children}</span></p>
);

function Anomalies({ id }: { id: string }) {
  const [rate, setRate] = useState("0.01");
  const { data, error, loading } = useApi<any>(`/datasets/${id}/patterns/anomalies?contamination=${rate}`);
  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <Skeleton className="h-80" />;
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader><div><CardTitle>Unusual rows</CardTitle><CardDescription>{data.method}</CardDescription></div>
          <Select className="w-44" value={rate} onChange={(e) => setRate(e.target.value)} aria-label="Share to flag">
            {["0.005", "0.01", "0.02", "0.05"].map((r) => <option key={r} value={r}>Flag {(+r * 100).toFixed(1)}% of rows</option>)}</Select></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-[13.5px] text-fg"><b className="num">{data.flagged.toLocaleString()}</b> of {data.rows_checked.toLocaleString()} rows flagged{data.rows_skipped_missing ? ` (${data.rows_skipped_missing.toLocaleString()} rows with missing values were not checked)` : ""}.</p>
          <Note warn>{data.caveat}</Note>
          {data.scatter && <ChartRenderer spec={{ id: "an", kind: "scatter", title: `${data.scatter.y} vs ${data.scatter.x} (sample; flagged rows highlighted)`, data: data.scatter.points, x: "x", series: [{ key: "y" }], x_label: data.scatter.x, y_label: data.scatter.y, group: "group" }} height={280} />}
          <DataGrid dense maxHeight={360} columns={["row", "score", "why", ...data.columns.slice(0, 6)]} rows={data.top.map((t: any) => ({ ...t, why: t.why.join("; ") }))} />
        </CardContent>
      </Card>
      {data.periods && (
        <Card>
          <CardHeader><div><CardTitle>Unusual days</CardTitle><CardDescription>{data.periods.method}</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <ChartRenderer spec={{ id: "anp", kind: "line", title: `Daily total ${data.periods.measure}`, data: data.periods.series, x: "period", series: [{ key: "value", label: data.periods.measure }], highlight: data.periods.hits.map((h: any) => h.period) }} height={240} />
            {data.periods.hits.length ? <DataGrid dense columns={["period", "value", "typical", "z"]} rows={data.periods.hits} /> : <Note>No day was more than {data.periods.threshold} robust standard deviations from its neighbours.</Note>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Forecast({ id, dataset }: { id: string; dataset: any }) {
  const dates: string[] = dataset.profile.datetime_columns || [];
  const nums: string[] = dataset.profile.numeric_columns || [];
  const [grain, setGrain] = useState("month");
  const [measure, setMeasure] = useState<string>("");
  const { data, error, loading } = useApi<any>(dates.length ? `/datasets/${id}/patterns/forecast?grain=${grain}${measure ? `&measure=${encodeURIComponent(measure)}` : ""}` : null);
  if (!dates.length) return <Card className="p-8 text-center text-[13px] text-fg-3">This dataset has no date column, so there is nothing to forecast.</Card>;
  return (
    <Card>
      <CardHeader><div><CardTitle>Forecast</CardTitle><CardDescription>{data?.method || "Models are tested on the most recent periods before forecasting."}</CardDescription></div>
        <div className="flex gap-2">
          <Select className="w-40" value={measure} onChange={(e) => setMeasure(e.target.value)} aria-label="Measure"><option value="">{data?.measure ? `Total ${data.measure}` : "Default measure"}</option>{nums.map((n) => <option key={n} value={n}>Total {n}</option>)}</Select>
          <Select className="w-32" value={grain} onChange={(e) => setGrain(e.target.value)} aria-label="Grain">{["day", "week", "month", "quarter"].map((g) => <option key={g} value={g}>By {g}</option>)}</Select>
        </div></CardHeader>
      <CardContent className="space-y-3">
        {error ? <ErrorNote message={error} /> : loading || !data ? <Skeleton className="h-72" /> : <>
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <Badge tone={data.beats_naive ? "success" : "warning"}>{data.beats_naive ? `${humanize(data.best_model)} beat the naive forecast` : "No model clearly beat the naive forecast"}</Badge>
            <span className="text-fg-3">{data.periods} {grain}s of history, tested on the last {data.holdout}, forecasting {data.horizon} ahead.</span>
          </div>
          <ChartRenderer spec={{ id: "fc", kind: "forecast", title: `${data.measure ? `Total ${data.measure}` : "Rows"} per ${grain}`, data: data.series, x: "period", series: [{ key: "actual", label: "Actual" }, { key: "forecast", label: "Forecast" }], band: ["low", "high"], band_label: "Approximate range (holdout errors)" }} height={280} />
          {data.notes.map((n: string) => <Note key={n} warn>{n}</Note>)}
          <Note>{data.interval}</Note>
          <DataGrid dense columns={["model", "mae", "mape_pct"]} rows={data.models.map((m: any) => ({ ...m, model: m.model === data.best_model ? `${humanize(m.model)} (chosen)` : humanize(m.model), mae: m.error ? `failed (${m.error})` : m.mae }))} />
        </>}
      </CardContent>
    </Card>
  );
}

function Segments({ id }: { id: string }) {
  const { data, error, loading } = useApi<any>(`/datasets/${id}/patterns/segments`);
  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <Skeleton className="h-80" />;
  return (
    <Card>
      <CardHeader><div><CardTitle>Segments</CardTitle><CardDescription>{data.method}</CardDescription></div></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <Badge tone={data.strength === "clear" ? "success" : data.strength === "moderate" ? "accent" : "warning"}>{data.k} segments, {data.strength} separation</Badge>
          <span className="text-fg-3">silhouette {data.silhouette} on {data.rows_used.toLocaleString()} rows using {data.columns.join(", ")}</span>
        </div>
        <Note warn={data.strength === "weak"}>{data.caveat}</Note>
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartRenderer spec={{ id: "seg", kind: "scatter", title: "Rows on the first two principal components, coloured by segment", data: data.projection, x: "x", series: [{ key: "y" }], x_label: "Component 1", y_label: "Component 2", group: "group" }} height={300} />
          <div className="space-y-2">
            {data.segments.map((s: any) => (
              <div key={s.segment} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between text-[13px]"><b className="text-fg">Segment {s.segment}</b><span className="num text-fg-3">{s.rows.toLocaleString()} rows ({(s.share * 100).toFixed(1)}%)</span></div>
                <ul className="mt-1 text-[12.5px] text-fg-2">{s.distinctive.map((d: string) => <li key={d}>• {d}</li>)}</ul>
              </div>
            ))}
          </div>
        </div>
        <details className="text-[12.5px] text-fg-3"><summary className="cursor-pointer">Silhouette by number of segments</summary>
          <div className="mt-2 max-w-sm"><DataGrid dense columns={["k", "silhouette"]} rows={data.tries} /></div></details>
      </CardContent>
    </Card>
  );
}

export function PatternsView({ dataset }: { dataset: any }) {
  const [view, setView] = useState<"anomalies" | "forecast" | "segments">("anomalies");
  return (
    <div className="space-y-4">
      <Tabs value={view} onChange={setView} items={[{ value: "anomalies", label: "Anomalies" }, { value: "forecast", label: "Forecast" }, { value: "segments", label: "Segments" }]} />
      {view === "anomalies" && <Anomalies id={dataset.id} />}
      {view === "forecast" && <Forecast id={dataset.id} dataset={dataset} />}
      {view === "segments" && <Segments id={dataset.id} />}
    </div>
  );
}
