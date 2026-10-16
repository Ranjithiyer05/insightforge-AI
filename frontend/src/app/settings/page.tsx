"use client";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Bot, Cpu, Download, Lock, Monitor, Moon, Palette, Sun, Trash2, BrainCircuit } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-center justify-between border-b border-border/70 py-2 text-[13px] last:border-0"><span className="text-fg-3">{k}</span><span className="text-fg">{v}</span></div>;
}

export default function SettingsPage() {
  const { data: s, reload } = useApi<any>("/settings");
  const { data: modes } = useApi<any[]>("/agent-modes");
  const { theme, setTheme } = useTheme();
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [wipe, setWipe] = useState("");
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!s) return <Skeleton className="h-96" />;
  const put = async (body: any) => {
    setErr(null);
    try { await api("/settings", { method: "PUT", json: body }); setMsg("Saved."); reload(); setTimeout(() => setMsg(null), 1500); } catch (e: any) { setErr(e.message); }
  };
  const exportMemory = async () => {
    const data = await api("/export/memory");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "insightforge_memory.json"; a.click(); URL.revokeObjectURL(url);
  };
  const doWipe = async () => {
    try { await api("/data/wipe", { method: "POST", json: { confirm: wipe } }); setWipe(""); setMsg("All your data was deleted."); } catch (e: any) { setErr(e.message); }
  };
  return (
    <div className="space-y-6 animate-in">
      <PageHeader title="Settings" description="Model provider, execution limits, privacy, memory and appearance." actions={msg && <Badge tone="success">{msg}</Badge>} />
      {err && <ErrorNote message={err} />}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Bot className="size-4" /> Model and provider</CardTitle><CardDescription>Configured on the server with environment variables. Keys are never sent to the browser.</CardDescription></div>
            <Badge tone={s.llm.configured ? "success" : "neutral"}>{s.llm.configured ? "Configured" : "Not configured"}</Badge></CardHeader>
          <CardContent>
            <Row k="Provider" v={s.llm.provider} /><Row k="Model" v={s.llm.model || "—"} />
            <p className="mt-3 text-[12.5px] text-fg-3">{s.llm.message}</p>
            <p className="mt-2 text-[12.5px] text-fg-3">Free options: set <code>LLM_PROVIDER=ollama</code> to use local models through Ollama, or <code>openai_compatible</code> with <code>LLM_BASE_URL</code> for any free OpenAI-compatible endpoint. Variables: {s.editable_via_env.join(", ")}.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><BrainCircuit className="size-4" /> Agent and memory</CardTitle><CardDescription>How the agent plans, retries and uses experience.</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5"><Label>Agent configuration</Label>
              <Select value={s.agent.agent_mode} onChange={(e) => put({ agent_mode: e.target.value })}>{modes?.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</Select></div>
            <div className="space-y-1.5"><Label>Default retry budget</Label>
              <Select value={s.agent.retry_budget} onChange={(e) => put({ retry_budget: Number(e.target.value) })}>{[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} retries</option>)}</Select></div>
            <label className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-[13px]"><span>Use experience memory<div className="text-[12px] text-fg-3">Off runs every new analysis as the no-memory baseline.</div></span>
              <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={s.agent.memory_enabled} onChange={(e) => put({ memory_enabled: e.target.checked })} /></label>
            <Button variant="secondary" size="sm" onClick={exportMemory}><Download /> Export my memory (JSON)</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Cpu className="size-4" /> Execution limits</CardTitle><CardDescription>Every generated script runs in a restricted sandbox.</CardDescription></div></CardHeader>
          <CardContent>
            <Row k="Timeout per step" v={`${s.execution.sandbox_timeout_s}s`} /><Row k="Memory limit" v={`${s.execution.sandbox_memory_mb} MB`} />
            <Row k="Network access" v={s.execution.network_isolation ? <Badge tone="success">Blocked (network namespace + audit hook)</Badge> : <Badge tone="warning">Blocked by audit hook only</Badge>} />
            <Row k="Max upload" v={`${s.execution.max_upload_mb} MB`} /><Row k="Max rows" v={s.execution.max_rows.toLocaleString()} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Lock className="size-4" /> Privacy</CardTitle></div></CardHeader>
          <CardContent>
            <Row k="Dataset retention" v={s.privacy.retention_days > 0 ? `${s.privacy.retention_days} days` : "Until you delete"} />
            <Row k="Sample rows sent to LLM" v={s.privacy.llm_sample_rows ? "Allowed" : "Never"} />
            <p className="mt-2 text-[12.5px] text-fg-3">{s.privacy.storage} Datasets are private to your account; administrators can manage accounts but cannot open your data.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Palette className="size-4" /> Appearance</CardTitle></div></CardHeader>
          <CardContent className="flex gap-2">
            {[["light", Sun, "Light"], ["dark", Moon, "Dark"], ["system", Monitor, "System"]].map(([v, I, l]: any) => (
              <button key={v} onClick={() => setTheme(v)} className={cn("flex flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-[13px]", mounted && theme === v ? "border-accent bg-accent-soft text-accent-text" : "border-border text-fg-2 hover:bg-surface-2")}><I className="size-4" /> {l}</button>
            ))}
          </CardContent>
        </Card>
        <Card className="border-danger/30">
          <CardHeader><div><CardTitle className="flex items-center gap-2 text-danger"><Trash2 className="size-4" /> Delete all my data</CardTitle><CardDescription>Removes your datasets, analyses, experiments, lessons and evaluations. This cannot be undone.</CardDescription></div></CardHeader>
          <CardContent className="flex gap-2"><Input value={wipe} onChange={(e) => setWipe(e.target.value)} placeholder="Type DELETE ALL" /><Button variant="danger" disabled={wipe !== "DELETE ALL"} onClick={doWipe}>Delete</Button></CardContent>
        </Card>
      </div>
    </div>
  );
}
