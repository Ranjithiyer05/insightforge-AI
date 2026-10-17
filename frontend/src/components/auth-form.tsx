"use client";
import { Logo } from "@/components/logo";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Sparkles, ShieldCheck, FlaskConical, BrainCircuit } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "./auth";
import { Button } from "./ui/button";
import { Input, Label } from "./ui/input";
import { ErrorNote } from "./ui/misc";

function Form({ mode }: { mode: "login" | "register" }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const sp = useSearchParams();
  const { setUser } = useAuth();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const u = await api(`/auth/${mode}`, { method: "POST", json: mode === "login" ? { email, password } : { email, password, name } });
      setUser(u);
      const next = sp.get("next");
      router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      {mode === "register" && <div className="space-y-1.5"><Label htmlFor="name">Name</Label><Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></div>}
      <div className="space-y-1.5"><Label htmlFor="email">Email</Label><Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></div>
      <div className="space-y-1.5"><Label htmlFor="pw">Password</Label><Input id="pw" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
        {mode === "register" && <p className="text-[12px] text-fg-3">At least 8 characters.</p>}</div>
      {err && <ErrorNote message={err} />}
      <Button type="submit" className="w-full" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</Button>
      <p className="text-center text-[13px] text-fg-3">
        {mode === "login" ? <>New here? <Link className="text-accent-text hover:underline" href="/register">Create an account</Link></> : <>Already have an account? <Link className="text-accent-text hover:underline" href="/login">Sign in</Link></>}
        <span className="mt-1 block">Just looking? <Link className="text-accent-text hover:underline" href="/welcome">Try the guest demo</Link></span>
      </p>
    </form>
  );
}

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between border-r border-border bg-surface p-10 lg:flex">
        <Logo tagline={false} />
        <div className="max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">An autonomous data scientist that shows its work.</h2>
          <p className="mt-3 text-fg-2">Ask a question in plain English. InsightForge plans the analysis, runs real code in a sandbox, verifies every number independently and learns only from validated experience.</p>
          <ul className="mt-8 space-y-4 text-sm text-fg-2">
            <li className="flex gap-3"><FlaskConical className="mt-0.5 size-4 text-accent-text" /> Statistical tests, ML models and forecasts chosen for your question</li>
            <li className="flex gap-3"><ShieldCheck className="mt-0.5 size-4 text-accent-text" /> Independent verification of results, assumptions and evidence</li>
            <li className="flex gap-3"><BrainCircuit className="mt-0.5 size-4 text-accent-text" /> Failure-aware memory you can inspect, correct and delete</li>
          </ul>
        </div>
        <p className="text-xs text-fg-3">Your datasets are private to your account.</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <h1 className="text-xl font-semibold tracking-tight">{mode === "login" ? "Sign in" : "Create your account"}</h1>
          <p className="mb-6 mt-1 text-sm text-fg-3">{mode === "login" ? "Welcome back to your analysis workspace." : "Start analysing your data in minutes."}</p>
          <Suspense><Form mode={mode} /></Suspense>
        </div>
      </div>
    </div>
  );
}
