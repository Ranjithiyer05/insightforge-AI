"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, BarChart3, BrainCircuit, CheckCircle2, Code2, FileText, Lock, MessageSquareText, ShieldCheck, Sparkles, Wand2, FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ErrorNote } from "@/components/ui/misc";
import { Stagger, StaggerItem, motion } from "@/components/motion";

const FEATURES = [
  { icon: Wand2, title: "Profile and clean, transparently", text: "Types, missing values, duplicates, outliers and inconsistent spellings are detected for you. Every cleaning step is shown, reversible and logged." },
  { icon: MessageSquareText, title: "Ask questions in plain English", text: "Questions become an editable plan that runs real pandas, SQL, SciPy and scikit-learn code. You can read every line." },
  { icon: ShieldCheck, title: "Every number re-checked", text: "An independent verifier recomputes key figures from your raw file before they reach the report. Numbers that do not match are flagged." },
  { icon: FlaskConical, title: "Models evaluated honestly", text: "Leakage-safe pipelines, cross-validation on training data only, a held-out test set and a majority or mean baseline to beat." },
  { icon: FileText, title: "Reports you can hand over", text: "PDF reports, CSV tables and a code bundle that reproduces each step, plus read-only share links you can revoke." },
  { icon: Lock, title: "Private and free to run", text: "Your data stays on the server and is private to your account. No paid AI service is needed; an LLM is optional." },
];

const STEPS = ["Upload", "Profile", "Clean", "Explore", "Ask", "Model", "Verify", "Report"];

export default function Welcome() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const tryDemo = async () => {
    setBusy(true); setErr(null);
    try {
      const g = await api("/auth/guest", { method: "POST" });
      router.push(`/datasets/${g.dataset_id}`);
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <div className="min-h-screen bg-bg text-fg">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <div className="flex items-center gap-2.5"><div className="flex size-9 items-center justify-center rounded-xl grad-accent text-white"><Sparkles className="size-[18px]" /></div><span className="text-[15px] font-semibold">InsightForge</span></div>
        <nav className="flex items-center gap-2">
          <Link href="/login" className="rounded-lg px-3 py-1.5 text-[13.5px] text-fg-2 hover:bg-surface-2 hover:text-fg">Sign in</Link>
          <Button asChild size="sm"><Link href="/register">Create account</Link></Button>
        </nav>
      </header>

      <section className="relative mx-auto max-w-6xl px-5 pb-16 pt-10 sm:pt-16">
        <Stagger className="max-w-3xl">
          <StaggerItem><span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1 text-[12px] text-fg-2"><CheckCircle2 className="size-3.5 text-success" /> Free and open source · no API key required</span></StaggerItem>
          <StaggerItem><h1 className="mt-5 text-[38px] font-semibold leading-[1.08] tracking-tight sm:text-[54px]">Upload a dataset. Get analysis <span className="text-accent">you can check.</span></h1></StaggerItem>
          <StaggerItem><p className="mt-5 max-w-2xl text-[16px] leading-relaxed text-fg-2">InsightForge profiles your data, helps you clean it, answers business questions with real code, evaluates models properly and writes a report where every key number has been recomputed from the raw file.</p></StaggerItem>
          <StaggerItem>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button size="lg" onClick={tryDemo} disabled={busy}>{busy ? "Preparing the demo…" : <>Try the live demo <ArrowRight /></>}</Button>
              <Button size="lg" variant="secondary" asChild><Link href="/register">Use my own data</Link></Button>
            </div>
            <p className="mt-3 text-[12.5px] text-fg-3">The demo opens a temporary guest workspace with a synthetic retail dataset. It is deleted automatically within a day.</p>
            {err && <div className="mt-3 max-w-md"><ErrorNote message={err} /></div>}
          </StaggerItem>
        </Stagger>

        <motion.ol initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4, duration: 0.5 }}
          className="mt-14 flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-surface p-4 shadow-card" aria-label="Analysis pipeline">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-2 text-[13px]">
              <span className="flex size-6 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent-text">{i + 1}</span>
              <span className="font-medium">{s}</span>
              {i < STEPS.length - 1 && <ArrowRight className="size-3.5 text-fg-3" />}
            </li>
          ))}
        </motion.ol>
      </section>

      <section className="border-t border-border bg-surface/50">
        <div className="mx-auto max-w-6xl px-5 py-16">
          <h2 className="text-[24px] font-semibold tracking-tight">What it does</h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <motion.div key={f.title} initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }} transition={{ delay: i * 0.05, duration: 0.4 }}
                className="rounded-2xl border border-border bg-surface p-5 shadow-card">
                <div className="flex size-9 items-center justify-center rounded-xl bg-accent-soft text-accent-text"><f.icon className="size-[18px]" /></div>
                <h3 className="mt-3 text-[15px] font-semibold">{f.title}</h3>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-fg-2">{f.text}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-16">
        <div className="grid gap-8 lg:grid-cols-2">
          <div>
            <h2 className="text-[24px] font-semibold tracking-tight">How it is built</h2>
            <ul className="mt-5 space-y-3 text-[14px] text-fg-2">
              <li className="flex gap-2"><Code2 className="mt-0.5 size-4 shrink-0 text-accent" /> Next.js and React frontend; FastAPI backend with pandas, SciPy, statsmodels and scikit-learn.</li>
              <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" /> Analysis scripts run in a sandboxed subprocess with an import allowlist, resource limits and an audit hook.</li>
              <li className="flex gap-2"><BrainCircuit className="mt-0.5 size-4 shrink-0 text-accent" /> An optional LLM can refine plans and wording, but never produces the numbers.</li>
              <li className="flex gap-2"><BarChart3 className="mt-0.5 size-4 shrink-0 text-accent" /> Charts are drawn from computed rows only; nothing is invented.</li>
            </ul>
          </div>
          <div className="rounded-2xl border border-border bg-surface p-5 shadow-card">
            <h3 className="text-[15px] font-semibold">Limitations, stated plainly</h3>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[13.5px] text-fg-2">
              <li>Files up to the server's upload limit and about one million rows.</li>
              <li>Statistical associations are not causal effects, and the app says so where it matters.</li>
              <li>On free hosting the server sleeps when idle, so the first request can take up to a minute.</li>
            </ul>
          </div>
        </div>
      </section>
      <footer className="border-t border-border py-6 text-center text-[12px] text-fg-3">InsightForge · <a className="underline" href="https://github.com/Ranjithiyer05/insightforge-AI">Source on GitHub</a></footer>
    </div>
  );
}
