"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDownRight, ArrowUpRight, Bell, Boxes, Database, FlaskConical, MessageSquareText, Minus } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { AnimatedNumber, motion } from "./motion";
import { StatusBadge } from "./status";

export type Range = "7" | "30" | "90";
export const METRICS = [
  { key: "analyses", label: "Analyses run", icon: FlaskConical, color: "var(--chart-1)" },
  { key: "datasets", label: "Datasets added", icon: Database, color: "var(--chart-2)" },
  { key: "questions", label: "Questions asked", icon: MessageSquareText, color: "var(--chart-3)" },
  { key: "models", label: "Models trained", icon: Boxes, color: "var(--chart-4)" },
] as const;
type MetricKey = (typeof METRICS)[number]["key"];

/** Bucket the last `range` days of the daily series: daily for 7/30 days, weekly for 90. */
export function bucket(series: any[], range: Range) {
  const rows = series.slice(-Number(range));
  if (range !== "90") return rows;
  const out: any[] = [];
  for (let i = 0; i < rows.length; i += 7) {
    const chunk = rows.slice(i, i + 7);
    const r: any = { date: chunk[0].date };
    for (const m of METRICS) r[m.key] = chunk.reduce((s, x) => s + x[m.key], 0);
    out.push(r);
  }
  return out;
}

const fmtDay = (d: string) => new Date(d + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });

function Trend({ pct, prev, cur }: { pct: number | null; prev: number; cur: number }) {
  if (pct === null) return <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[11.5px] font-medium text-fg-3" title="No activity in the previous period to compare with"><Minus className="size-3" />{cur > 0 ? "new" : "flat"}</span>;
  const up = pct > 0, flat = pct === 0;
  return (
    <span className={cn("inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11.5px] font-semibold num", flat ? "bg-surface-2 text-fg-3" : up ? "bg-success-soft text-success" : "bg-danger-soft text-danger")}>
      {flat ? <Minus className="size-3" /> : up ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}{Math.abs(pct)}%
    </span>
  );
}

export function KpiCard({ metric, win, spark, range, active, onSelect, index }: { metric: (typeof METRICS)[number]; win: any; spark: any[]; range: Range; active: boolean; onSelect: () => void; index: number }) {
  const max = Math.max(1, ...spark.map((r) => r[metric.key]));
  const Icon = metric.icon;
  return (
    <button type="button" onClick={onSelect} aria-pressed={active}
      className={cn("kpi group relative w-full rounded-xl border bg-surface p-4 text-left shadow-card transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
        active ? "border-accent/60" : "border-border hover:border-border-strong")}>
      <span className="hud-corners" aria-hidden="true" />
      <div className="flex items-center justify-between">
        <span className="hud-label flex min-w-0 items-center gap-2 truncate whitespace-nowrap"><b>{String(index + 1).padStart(2, "0")}</b>{metric.label}<Icon className="size-3.5" /></span>
        <Trend pct={win?.change_pct ?? null} prev={win?.previous ?? 0} cur={win?.current ?? 0} />
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <div className="font-display text-[44px] font-medium leading-none tracking-tighter text-fg num"><AnimatedNumber value={win?.current} /></div>
          <div className="mt-1.5 text-[11.5px] text-fg-3">vs <span className="num">{win?.previous ?? 0}</span> in the previous {range} days</div>
        </div>
        <div className="flex h-10 items-end gap-[3px]" aria-hidden="true">
          {spark.slice(-14).map((r, i) => (
            <motion.span key={r.date} className="w-[5px] rounded-sm" style={{ background: active ? "var(--accent)" : "var(--text)", opacity: r[metric.key] ? 0.9 : 0.15 }}
              initial={{ height: 2 }} animate={{ height: Math.max(2, (r[metric.key] / max) * 40) }} transition={{ delay: 0.15 + i * 0.025, type: "spring", stiffness: 260, damping: 24 }} />
          ))}
        </div>
      </div>
    </button>
  );
}

export function ActivityChart({ series, range, visible, onToggle }: { series: any[]; range: Range; visible: Set<MetricKey>; onToggle: (k: MetricKey) => void }) {
  const data = useMemo(() => bucket(series, range), [series, range]);
  const empty = data.every((r) => METRICS.every((m) => !r[m.key]));
  return (
    <Card className="scan-once overflow-hidden">
      <CardHeader className="flex-wrap">
        <div><div className="hud-label mb-1">[ <b>02</b> Telemetry ]</div><CardTitle>Workspace activity</CardTitle><CardDescription>{range === "90" ? "Weekly totals" : "Daily totals"} over the last {range} days. Click a series to show or hide it.</CardDescription></div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Series">
          {METRICS.map((m) => (
            <button key={m.key} onClick={() => onToggle(m.key)} aria-pressed={visible.has(m.key)}
              className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50", visible.has(m.key) ? "border-border-strong bg-surface text-fg" : "border-dashed border-border text-fg-3 opacity-60 hover:opacity-100")}>
              <span className="size-2 rounded-full" style={{ background: m.color }} />{m.label.split(" ")[0]}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="relative">
        <div className="h-[260px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
              <defs>{METRICS.map((m) => <linearGradient key={m.key} id={`g-${m.key}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={m.color} stopOpacity={0.35} /><stop offset="100%" stopColor={m.color} stopOpacity={0} /></linearGradient>)}</defs>
              <CartesianGrid vertical={false} strokeDasharray="3 4" />
              <XAxis dataKey="date" tickFormatter={fmtDay} tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} />
              <Tooltip cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }} content={({ active, payload, label }) => active && payload?.length ? (
                <div className="rounded-xl border border-border bg-surface/95 px-3 py-2 text-[12px] shadow-card backdrop-blur">
                  <div className="mb-1 font-medium text-fg">{range === "90" ? `Week of ${fmtDay(label as string)}` : fmtDay(label as string)}</div>
                  {payload.map((p: any) => <div key={p.dataKey} className="flex items-center justify-between gap-4 text-fg-2"><span className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: p.color }} />{METRICS.find((m) => m.key === p.dataKey)?.label}</span><b className="num text-fg">{p.value}</b></div>)}
                </div>) : null} />
              {METRICS.filter((m) => visible.has(m.key)).map((m) => (
                <Area key={m.key} type="monotone" dataKey={m.key} stroke={m.color} strokeWidth={2} fill={`url(#g-${m.key})`} animationDuration={900} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
        {empty && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[13px] text-fg-3">No activity in this period yet.</div>}
      </CardContent>
    </Card>
  );
}

const STATUS = [
  { key: "completed", label: "Completed", color: "var(--success)" },
  { key: "needs_review", label: "Needs review", color: "var(--warning)" },
  { key: "failed", label: "Failed", color: "var(--danger)" },
  { key: "other", label: "In progress or draft", color: "var(--chart-5)" },
];

export function StatusDonut({ counts }: { counts: any }) {
  const [hover, setHover] = useState<number | null>(null);
  const other = Math.max(0, counts.analyses - counts.completed - counts.needs_review - counts.failed);
  const rows = STATUS.map((s) => ({ ...s, value: s.key === "other" ? other : counts[s.key] }));
  const total = counts.analyses;
  const shown = hover !== null ? rows[hover] : null;
  return (
    <Card>
      <CardHeader><div><div className="hud-label mb-1">[ <b>03</b> Outcomes ]</div><CardTitle>Analysis outcomes</CardTitle><CardDescription>All analyses in your workspace.</CardDescription></div></CardHeader>
      <CardContent>
        <div className="relative mx-auto h-[170px] w-[170px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={total ? rows : [{ value: 1 }]} dataKey="value" innerRadius={56} outerRadius={80} paddingAngle={total ? 2 : 0} stroke="none" animationDuration={900}
                onMouseEnter={(_, i) => total && setHover(i)} onMouseLeave={() => setHover(null)}>
                {total ? rows.map((r, i) => <Cell key={r.key} fill={r.color} opacity={hover === null || hover === i ? 1 : 0.35} />) : <Cell fill="var(--surface-3)" />}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <div className="text-[24px] font-semibold text-fg num">{shown ? shown.value : <AnimatedNumber value={total} />}</div>
            <div className="text-[11px] text-fg-3">{shown ? shown.label : "analyses"}</div>
          </div>
        </div>
        <ul className="mt-4 space-y-1">
          {rows.map((r, i) => (
            <li key={r.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className={cn("flex items-center justify-between rounded-lg px-2 py-1 text-[12.5px] transition", hover === i && "bg-surface-2")}>
              <span className="flex items-center gap-2 text-fg-2"><span className="size-2.5 rounded-sm" style={{ background: r.color }} />{r.label}</span>
              <span className="num text-fg">{r.value}<span className="ml-1.5 text-fg-3">{total ? Math.round((r.value / total) * 100) : 0}%</span></span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

const FEED_ICON: Record<string, any> = { analysis: FlaskConical, question: MessageSquareText, model: Boxes, alert: Bell };
const FEED_TONE: Record<string, string> = { analysis: "bg-accent-soft text-accent-text", question: "bg-warning-soft text-warning", model: "bg-info-soft text-info", alert: "bg-danger-soft text-danger" };

export function ActivityFeed({ items }: { items: any[] }) {
  return (
    <Card>
      <CardHeader><div><div className="hud-label mb-1">[ <b>05</b> Log ]</div><CardTitle>Recent activity</CardTitle><CardDescription>Analyses, questions, models and alerts.</CardDescription></div></CardHeader>
      <CardContent>
        {items.length ? (
          <ol className="relative space-y-0.5 before:absolute before:left-[15px] before:top-3 before:bottom-3 before:w-px before:bg-border">
            {items.map((f, i) => {
              const Icon = FEED_ICON[f.kind];
              return (
                <motion.li key={f.kind + f.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}>
                  <Link href={f.href} className="relative flex items-start gap-3 rounded-lg py-1.5 pr-2 transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50">
                    <span className={cn("relative z-10 flex size-[30px] shrink-0 items-center justify-center rounded-full ring-4 ring-surface", FEED_TONE[f.kind])}><Icon className="size-3.5" /></span>
                    <span className="min-w-0 flex-1 pt-0.5">
                      <span className="line-clamp-1 text-[13px] text-fg">{f.title}</span>
                      <span className="text-[11.5px] text-fg-3">{f.kind === "alert" ? "Alert" : f.kind[0].toUpperCase() + f.kind.slice(1)} · {timeAgo(f.at)}</span>
                    </span>
                    {f.kind === "analysis" && <StatusBadge status={f.status} />}
                  </Link>
                </motion.li>
              );
            })}
          </ol>
        ) : <p className="py-6 text-center text-[13px] text-fg-3">Nothing yet. Your work will show up here.</p>}
      </CardContent>
    </Card>
  );
}

/** A scrolling strip of real workspace numbers, in the style of a race-timing ticker. */
export function Ticker({ items }: { items: { label: string; value: string | number }[] }) {
  const row = items.map((it, i) => (
    <span key={i} className="flex items-center gap-2 px-6 font-mono text-[11.5px] uppercase tracking-[0.14em] text-fg-3">
      <span className="size-1.5 rounded-full bg-accent" />{it.label}<b className="font-medium text-fg num">{it.value}</b>
    </span>
  ));
  return (
    <div className="marquee relative overflow-hidden border-y border-border py-2.5 [mask-image:linear-gradient(90deg,transparent,black_8%,black_92%,transparent)]" aria-label="Workspace totals">
      <div className="marquee-track" aria-hidden="true">{row}{row}{row}{row}</div>
      <ul className="sr-only">{items.map((it, i) => <li key={i}>{it.label}: {it.value}</li>)}</ul>
    </div>
  );
}
