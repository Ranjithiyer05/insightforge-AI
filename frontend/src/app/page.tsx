"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, Beaker, BrainCircuit, CheckCircle2, Code2, Database, FlaskConical, FolderPlus, ListChecks, Play, ScanSearch, ShieldCheck, ShoppingCart, Sparkles, Users, TrendingDown, LineChart, Scale, Shapes, BarChart3 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { timeAgo } from "@/lib/utils";
import { DEMO_QUESTION, startDemo } from "@/lib/demo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorNote, Skeleton } from "@/components/ui/misc";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/components/auth";
import { AnimatedNumber, Stagger, StaggerItem } from "@/components/motion";
import { useWorkspace } from "@/components/workspace";
import { Tabs } from "@/components/ui/misc";
import { ActivityChart, ActivityFeed, KpiCard, METRICS, Range, StatusDonut, bucket } from "@/components/overview-widgets";

const EXAMPLES = [
  { q: DEMO_QUESTION, tag: "Retail", icon: TrendingDown, tone: "text-fg-2 bg-surface-2 ring-1 ring-inset ring-border" },
  { q: "Which customers are likely to churn?", tag: "Churn", icon: Users, tone: "text-fg-2 bg-surface-2 ring-1 ring-inset ring-border" },
  { q: "Is there a significant difference in tenure between churned and retained customers?", tag: "Hypothesis test", icon: Scale, tone: "text-fg-2 bg-surface-2 ring-1 ring-inset ring-border" },
  { q: "Forecast revenue for the next 3 months", tag: "Forecasting", icon: LineChart, tone: "text-fg-2 bg-surface-2 ring-1 ring-inset ring-border" },
  { q: "Compare revenue by region", tag: "Comparison", icon: BarChart3, tone: "text-fg-2 bg-surface-2 ring-1 ring-inset ring-border" },
  { q: "Segment our customers", tag: "Segmentation", icon: Shapes, tone: "text-fg-2 bg-surface-2 ring-1 ring-inset ring-border" },
];

const PIPELINE = [
  { icon: ScanSearch, title: "Profile", text: "Types, quality issues, leakage" },
  { icon: ListChecks, title: "Plan", text: "Editable, you approve it" },
  { icon: Code2, title: "Execute", text: "Python + SQL in a sandbox" },
  { icon: ShieldCheck, title: "Verify", text: "Numbers recomputed independently" },
  { icon: BrainCircuit, title: "Learn", text: "Only from validated evidence" },
];

function NewProject({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const { setCurrent } = useWorkspace();
  const create = async () => {
    try {
      const p = await api("/projects", { method: "POST", json: { name, description: desc } });
      setCurrent({ projectId: p.id, projectName: p.name, datasetId: null, datasetName: null });
      setOpen(false); setName(""); setDesc(""); onCreated();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="secondary" size="sm"><FolderPlus /> New project</Button></DialogTrigger>
      <DialogContent title="Create an analysis project" description="Projects group datasets and analyses for one piece of work.">
        <div className="space-y-3">
          <div className="space-y-1.5"><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Q2 profitability review" /></div>
          <div className="space-y-1.5"><Label>Description (optional)</Label><Textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} /></div>
          {err && <ErrorNote message={err} />}
          <div className="flex justify-end"><Button onClick={create} disabled={!name.trim()}>Create project</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function GettingStarted({ onDemo, busy }: { onDemo: () => void; busy: boolean }) {
  const steps = [
    { title: "Load data", text: "Upload a CSV or Excel file, or open the synthetic retail demo.", action: <Button size="sm" variant="secondary" asChild><Link href="/new">Upload a file</Link></Button> },
    { title: "Review its quality", text: "The dataset page shows types, missing values, duplicates and outliers, with one-click fixes you confirm first." },
    { title: "Ask a question", text: "Type a business question. You get an editable plan, then results with the code and checks behind them." },
  ];
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-[15px] font-semibold text-fg">Getting started</h2><p className="mt-0.5 text-[13px] text-fg-3">Three steps from a raw file to a checked answer.</p></div>
        <Button size="sm" onClick={onDemo} disabled={busy}><Play /> {busy ? "Preparing…" : "Run the demo instead"}</Button>
      </div>
      <Stagger className="mt-4 grid gap-3 md:grid-cols-3">
        {steps.map((st, i) => (
          <StaggerItem key={st.title} className="rounded-xl border border-border p-4">
            <div className="flex items-center gap-2 text-[13.5px] font-medium text-fg"><span className="flex size-6 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent-text">{i + 1}</span>{st.title}</div>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-fg-3">{st.text}</p>
            {st.action && <div className="mt-3">{st.action}</div>}
          </StaggerItem>
        ))}
      </Stagger>
    </Card>
  );
}

function Stat({ label, value, icon: Icon, hint, tone }: { label: string; value: any; icon: any; hint?: string; tone: string }) {
  return (
    <Card className="lift relative overflow-hidden p-5">
      <div className="flex items-start justify-between">
        <div className="text-[12.5px] font-medium text-fg-3">{label}</div>
        <div className={`flex size-9 items-center justify-center rounded-xl ${tone}`}><Icon className="size-[18px]" /></div>
      </div>
      <div className="mt-1 text-[30px] font-semibold leading-none tracking-tight num text-fg"><AnimatedNumber value={value} /></div>
      {hint && <div className="mt-2 text-[12px] text-fg-3">{hint}</div>}
    </Card>
  );
}

export default function Overview() {
  const { data, loading, reload } = useApi<any>("/overview");
  const { user } = useAuth();
  const { setCurrent } = useWorkspace();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("30");
  const [visible, setVisible] = useState<Set<any>>(() => new Set(METRICS.map((m) => m.key)));
  const [err, setErr] = useState<string | null>(null);
  const demo = async (which: "retail" | "churn", q?: string) => {
    setBusy(which); setErr(null);
    try { await startDemo(router.push, which, q); } catch (e: any) { setErr(e.message); setBusy(null); }
  };
  const c = data?.counts;
  const isNew = c && c.datasets === 0;

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const win = data?.windows?.[range];
  const spark = data?.series ? bucket(data.series, range === "7" ? "30" : range) : [];
  const toggle = (k: any) => setVisible((v) => { const n = new Set(v); if (n.has(k)) { if (n.size > 1) n.delete(k); } else n.add(k); return n; });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[12.5px] font-medium text-fg-3">{new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
          <h1 className="mt-0.5 text-[26px] font-semibold tracking-tight text-fg">{greet}{user?.name ? `, ${user.name.split(" ")[0]}` : ""}</h1>
          <p className="mt-0.5 text-[13.5px] text-fg-3">Here is what happened in your workspace.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={range} onChange={setRange} items={[{ value: "7", label: "7D" }, { value: "30", label: "30D" }, { value: "90", label: "90D" }]} />
          <NewProject onCreated={reload} />
          <Button size="sm" asChild><Link href="/new"><Play /> New analysis</Link></Button>
        </div>
      </div>

      {isNew && <>
      <section className="hero-panel relative overflow-hidden rounded-3xl px-6 py-8 animate-in text-white shadow-[0_30px_60px_-30px_rgba(40,30,120,0.6)] sm:px-10 sm:py-10">
        <div className="bg-dots pointer-events-none absolute inset-0 opacity-40 [mask-image:linear-gradient(to_bottom,black,transparent)]" />
        <div className="relative grid items-center gap-8 lg:grid-cols-[1.25fr_1fr]">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-[12px] font-medium text-white/90 backdrop-blur"><Sparkles className="size-3.5 text-[#c4b5fd]" /> Autonomous data scientist</span>
            <h1 className="mt-4 max-w-xl text-[30px] font-semibold leading-[1.12] tracking-tight sm:text-[38px]">
              {user?.name ? <>Welcome back, {user.name}.<br /></> : null}<span className="grad-text">Ask a question.</span> Get an analysis you can check.
            </h1>
            <p className="mt-3 max-w-xl text-[14.5px] leading-relaxed text-white/70">
              InsightForge profiles your data, proposes a plan you approve, runs real Python and SQL in a sandbox, verifies every key number and learns only from validated experiments.
            </p>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <Button size="lg" variant="white" asChild><Link href="/new"><Play /> Start an analysis</Link></Button>
              <Button size="lg" variant="ghost" onClick={() => demo("retail")} disabled={!!busy} className="border border-white/20 bg-white/10 text-white hover:bg-white/15 hover:text-white"><ShoppingCart /> {busy === "retail" ? "Preparing demo…" : "Run the retail demo"}</Button>
              <Button size="lg" variant="ghost" onClick={() => demo("churn", "Which customers are likely to churn?")} disabled={!!busy} className="text-white/80 hover:bg-white/10 hover:text-white"><Users /> {busy === "churn" ? "Preparing…" : "Churn demo"}</Button>
            </div>
            <p className="mt-3 text-[12px] text-white/50">Demo datasets are clearly labelled synthetic data and work without any API key.</p>
            {err && <div className="mt-3"><ErrorNote message={err} /></div>}
          </div>
          <div className="hidden rounded-2xl border border-white/12 bg-white/[0.06] p-4 backdrop-blur-md lg:block">
            <div className="mb-3 flex items-center justify-between text-[12px] text-white/60"><span className="font-medium text-white/85">How every analysis runs</span><span>5 stages</span></div>
            <ol className="space-y-2">
              {PIPELINE.map((p, i) => (
                <li key={p.title} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.05] px-3 py-2.5">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg grad-accent shadow-[0_4px_14px_-4px_rgba(139,92,246,0.9)]"><p.icon className="size-4" /></div>
                  <div className="min-w-0 flex-1"><div className="text-[13px] font-medium">{p.title}</div><div className="text-[11.5px] text-white/55">{p.text}</div></div>
                  <span className="num text-[11px] text-white/40">0{i + 1}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>
        <GettingStarted onDemo={() => demo("retail")} busy={!!busy} />
      </>}
      {!isNew && err && <ErrorNote message={err} />}

      {loading && !data ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[118px] rounded-2xl" />)}</div>
      ) : (
        <Stagger className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {METRICS.map((m) => (
            <StaggerItem key={m.key}><KpiCard metric={m} win={win?.[m.key]} spark={spark} range={range} active={visible.has(m.key) && visible.size === 1} onSelect={() => setVisible(visible.has(m.key) && visible.size === 1 ? new Set(METRICS.map((x) => x.key)) : new Set([m.key]))} /></StaggerItem>
          ))}
        </Stagger>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">{data?.series ? <ActivityChart series={data.series} range={range} visible={visible} onToggle={toggle} /> : <Skeleton className="h-[340px] rounded-2xl" />}</div>
        {c ? <StatusDonut counts={c} /> : <Skeleton className="h-[340px] rounded-2xl" />}
      </div>

      <Stagger className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StaggerItem><Stat label="Analyses completed" value={c?.completed} icon={CheckCircle2} tone="bg-success-soft text-success" hint={c ? `${c.needs_review} need review · ${c.failed} failed` : undefined} /></StaggerItem>
        <StaggerItem><Stat label="Datasets" value={c?.datasets} icon={Database} tone="bg-info-soft text-info" hint="Private to your account" /></StaggerItem>
        <StaggerItem><Stat label="Experiments run" value={c?.experiments} icon={Beaker} tone="bg-warning-soft text-warning" hint={data ? `${data.experiment_status.succeeded} succeeded · ${data.experiment_status.weak + data.experiment_status.invalid} weak/invalid` : undefined} /></StaggerItem>
        <StaggerItem><Stat label="Validated lessons" value={c?.lessons_validated} icon={BrainCircuit} tone="bg-accent-soft text-accent-text" hint={c ? `${c.lessons_candidate} candidate lessons` : undefined} /></StaggerItem>
      </Stagger>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div><CardTitle>Recent analyses</CardTitle><CardDescription>Every analysis keeps its full execution record.</CardDescription></div>
            <Button variant="ghost" size="sm" asChild><Link href="/analyses">View all <ArrowRight /></Link></Button>
          </CardHeader>
          <CardContent>
            {loading ? <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div> :
              data?.recent_analyses?.length ? (
                <ul className="space-y-0.5">
                  {data.recent_analyses.map((a: any) => (
                    <li key={a.id}>
                      <Link href={`/analyses/${a.id}`} className="-mx-2 flex items-center gap-3 rounded-xl px-2 py-3 transition hover:bg-surface-2">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text"><FlaskConical className="size-4" /></div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13.5px] font-medium text-fg">{a.question}</div>
                          <div className="text-[12px] text-fg-3">{a.task_label} · {timeAgo(a.created_at)}</div>
                        </div>
                        <StatusBadge status={a.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : <EmptyState icon={FlaskConical} title="No analyses yet" description="Upload a dataset or run the demo to see the full plan → execute → verify → learn loop." action={<Button size="sm" asChild><Link href="/new">Start an analysis</Link></Button>} />}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <ActivityFeed items={data?.activity ?? []} />
          <Card>
          <CardHeader><div><CardTitle>Try a question</CardTitle><CardDescription>Examples across domains.</CardDescription></div></CardHeader>
          <CardContent className="space-y-1.5">
            {EXAMPLES.map((e) => (
              <Link key={e.q} href={`/new?q=${encodeURIComponent(e.q)}`} className="group flex items-start gap-3 rounded-xl border border-border px-3 py-2.5 text-[13px] text-fg-2 transition hover:border-accent/40 hover:bg-accent-soft/30 hover:text-fg">
                <div className={`flex size-8 shrink-0 items-center justify-center rounded-lg ${e.tone}`}><e.icon className="size-4" /></div>
                <div className="min-w-0 flex-1"><div className="text-[10.5px] font-semibold uppercase tracking-wide text-fg-3">{e.tag}</div><div className="leading-snug">{e.q}</div></div>
                <ArrowRight className="mt-2 size-3.5 shrink-0 text-fg-3 opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
              </Link>
            ))}
          </CardContent>
        </Card>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><div><CardTitle>Projects</CardTitle><CardDescription>Group related datasets and questions.</CardDescription></div><NewProject onCreated={reload} /></CardHeader>
          <CardContent>
            {data?.recent_projects?.length ? (
              <ul className="space-y-1.5">
                {data.recent_projects.map((p: any) => (
                  <li key={p.id}><button onClick={() => { setCurrent({ projectId: p.id, projectName: p.name }); router.push("/new"); }} className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-left text-[13.5px] hover:bg-surface-2">
                    <span className="font-medium text-fg">{p.name}</span><span className="text-[12px] text-fg-3">{p.analyses} analyses · {timeAgo(p.created_at)}</span></button></li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-fg-3">{isNew ? "Create a project to organise your work, or just start an analysis." : "No projects yet."}</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Recently analysed datasets</CardTitle></div><Button variant="ghost" size="sm" asChild><Link href="/datasets">Library <ArrowRight /></Link></Button></CardHeader>
          <CardContent>
            {data?.recent_datasets?.length ? (
              <ul className="space-y-1.5">
                {data.recent_datasets.map((d: any) => (
                  <li key={d.id}><Link href={`/datasets/${d.id}`} className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-[13.5px] hover:bg-surface-2">
                    <span className="flex items-center gap-2 font-medium text-fg"><Database className="size-4 text-fg-3" />{d.name}{d.is_synthetic && <Badge tone="warning">Synthetic</Badge>}</span>
                    <span className="text-[12px] text-fg-3 num">{d.n_rows.toLocaleString()} rows · {d.n_cols} cols</span></Link></li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-fg-3">No datasets yet.</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
