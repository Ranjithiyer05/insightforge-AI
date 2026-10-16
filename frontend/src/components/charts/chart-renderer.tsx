"use client";
import { useState } from "react";
import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, ErrorBar, Legend, Line, LineChart, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, Cell,
} from "recharts";
import { Table2, LineChart as LineIcon } from "lucide-react";
import { DataGrid } from "../data-grid";
import { fmtNum } from "@/lib/utils";

export type ChartSpec = {
  id: string; kind: string; title: string; data: any[]; x: string; series: { key: string; label?: string }[];
  unit?: string; layout?: string; highlight?: string[]; error?: [string, string]; band?: [string, string];
  x_label?: string; y_label?: string; diagonal?: boolean; group?: string;
};

const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

function tickFmt(unit?: string) {
  return (v: any) => (typeof v === "number" ? (unit === "currency" ? fmtNum(v, { money: true }) : unit === "%" ? `${fmtNum(v)}%` : fmtNum(v)) : String(v).slice(0, 14));
}

function TooltipBox({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-card">
      <div className="mb-1 font-medium text-fg">{String(label ?? payload[0]?.payload?.x ?? "")}</div>
      {payload.filter((p: any) => p.value !== undefined && p.value !== null).map((p: any) => (
        <div key={p.dataKey + p.name} className="flex items-center gap-2 text-fg-2">
          <span className="size-2 rounded-full" style={{ background: p.color || p.fill || p.stroke }} />
          <span>{p.name}</span>
          <span className="ml-auto pl-3 num font-medium text-fg">{tickFmt(unit)(Array.isArray(p.value) ? p.value.join(" – ") : p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function ChartRenderer({ spec, height = 280 }: { spec: ChartSpec; height?: number }) {
  const [showData, setShowData] = useState(false);
  const fmt = tickFmt(spec.unit);
  const axis = { tickLine: false, axisLine: false, fontSize: 11 } as const;
  const horizontal = spec.layout === "horizontal";
  const hl = spec.highlight || [];
  let chart: React.ReactNode = null;

  if (spec.kind === "line") {
    chart = (
      <LineChart data={spec.data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey={spec.x} {...axis} minTickGap={20} type={spec.diagonal ? "number" : "category"} domain={spec.diagonal ? [0, 1] : undefined} />
        <YAxis {...axis} tickFormatter={fmt} width={64} domain={spec.diagonal ? [0, 1] : ["auto", "auto"]} />
        <Tooltip content={<TooltipBox unit={spec.unit} />} />
        {spec.series.length > 1 && <Legend iconType="circle" iconSize={8} />}
        {hl.length === 2 && <ReferenceArea x1={hl[0]} x2={hl[1]} fill="var(--accent)" fillOpacity={0.07} />}
        {spec.diagonal && <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--text-3)" strokeDasharray="4 4" />}
        {spec.series.map((s, i) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label || s.key} stroke={COLORS[i % 5]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />)}
      </LineChart>
    );
  } else if (spec.kind === "bar" || spec.kind === "stacked_bar") {
    const stacked = spec.kind === "stacked_bar";
    const data = spec.error ? spec.data.map((r) => ({ ...r, __err: [r[spec.series[0].key] - r[spec.error![0]], r[spec.error![1]] - r[spec.series[0].key]] })) : spec.data;
    chart = (
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 16, left: horizontal ? 8 : 4, bottom: 0 }} barCategoryGap="22%">
        <CartesianGrid horizontal={!horizontal} vertical={horizontal} strokeDasharray="3 3" />
        {horizontal ? (
          <>
            <XAxis type="number" {...axis} tickFormatter={fmt} />
            <YAxis type="category" dataKey={spec.x} {...axis} width={130} interval={0} />
          </>
        ) : (
          <>
            <XAxis dataKey={spec.x} {...axis} minTickGap={8} interval="preserveStartEnd" />
            <YAxis {...axis} tickFormatter={fmt} width={64} />
          </>
        )}
        <Tooltip content={<TooltipBox unit={spec.unit} />} cursor={{ fill: "var(--surface-2)" }} />
        {spec.series.length > 1 && <Legend iconType="circle" iconSize={8} />}
        <ReferenceLine {...(horizontal ? { x: 0 } : { y: 0 })} stroke="var(--border-strong)" />
        {spec.series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label || s.key} stackId={stacked ? "a" : undefined} fill={COLORS[i % 5]} radius={stacked ? 0 : 3} maxBarSize={42}>
            {!stacked && spec.series.length === 1 && data.map((r: any, j: number) => (
              <Cell key={j} fill={hl.includes(r[spec.x]) ? "var(--chart-4)" : (typeof r[s.key] === "number" && r[s.key] < 0 && spec.unit === "currency") ? "var(--chart-4)" : COLORS[0]} />
            ))}
            {spec.error && i === 0 && <ErrorBar dataKey="__err" width={6} stroke="var(--text-2)" direction={horizontal ? "x" : "y"} />}
          </Bar>
        ))}
      </BarChart>
    );
  } else if (spec.kind === "scatter") {
    const groups = spec.group ? Array.from(new Set(spec.data.map((d) => d[spec.group!]))) : [null];
    chart = (
      <ScatterChart margin={{ top: 8, right: 16, left: 4, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" dataKey="x" name={spec.x_label || "x"} {...axis} tickFormatter={fmt} label={{ value: spec.x_label, position: "insideBottom", offset: -4, fontSize: 11, fill: "var(--text-3)" }} />
        <YAxis type="number" dataKey="y" name={spec.y_label || "y"} {...axis} tickFormatter={fmt} width={64} />
        <Tooltip cursor={{ strokeDasharray: "3 3" }} content={<TooltipBox />} />
        {groups.length > 1 && <Legend iconType="circle" iconSize={8} />}
        {groups.map((g, i) => (
          <Scatter key={String(g)} name={g === null ? spec.y_label || "points" : `${spec.group} ${g}`} data={g === null ? spec.data : spec.data.filter((d) => d[spec.group!] === g)}
            fill={g === "anomaly" ? "var(--chart-4)" : COLORS[i % 5]} fillOpacity={0.6} />
        ))}
      </ScatterChart>
    );
  } else if (spec.kind === "forecast") {
    const data = spec.data.map((r) => ({ ...r, __band: r.lower !== undefined ? [r.lower, r.upper] : undefined }));
    chart = (
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey={spec.x} {...axis} minTickGap={24} />
        <YAxis {...axis} tickFormatter={fmt} width={64} />
        <Tooltip content={<TooltipBox />} />
        <Legend iconType="circle" iconSize={8} />
        <Area dataKey="__band" name="95% interval" stroke="none" fill="var(--chart-1)" fillOpacity={0.12} />
        <Line dataKey="actual" name="Actual" stroke="var(--chart-5)" strokeWidth={2} dot={false} />
        <Line dataKey="holdout_prediction" name="Holdout prediction" stroke="var(--chart-3)" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 2 }} />
        <Line dataKey="forecast" name="Forecast" stroke="var(--chart-1)" strokeWidth={2} dot={{ r: 2 }} />
      </ComposedChart>
    );
  }

  return (
    <figure className="rounded-xl border border-border bg-surface p-4">
      <figcaption className="mb-3 flex items-start justify-between gap-3">
        <span className="text-[13px] font-medium text-fg">{spec.title}</span>
        <button onClick={() => setShowData(!showData)} className="flex items-center gap-1 text-[11.5px] text-fg-3 hover:text-fg" aria-label="Toggle chart data table">
          {showData ? <LineIcon className="size-3.5" /> : <Table2 className="size-3.5" />} {showData ? "Chart" : "Data"}
        </button>
      </figcaption>
      {showData || !chart ? (
        <DataGrid columns={Object.keys(spec.data[0] || {}).filter((k) => !k.startsWith("__"))} rows={spec.data} maxHeight={height} dense />
      ) : (
        <div style={{ height: horizontal ? Math.max(height, spec.data.length * 30 + 40) : height }} role="img" aria-label={spec.title}>
          <ResponsiveContainer width="100%" height="100%">{chart as any}</ResponsiveContainer>
        </div>
      )}
      <p className="mt-2 text-[11px] text-fg-3">Computed from the dataset during execution · {spec.data.length} data points</p>
    </figure>
  );
}
