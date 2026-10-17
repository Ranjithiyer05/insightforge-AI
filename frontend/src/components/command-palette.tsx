"use client";
import * as D from "@radix-ui/react-dialog";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { ArrowRight, Database, FileText, History, LayoutDashboard, Moon, PlusCircle, Search, Settings, ShoppingCart, Sun, Users, Columns2, BrainCircuit, Beaker } from "lucide-react";
import { api } from "@/lib/api";
import { startDemo } from "@/lib/demo";
import { cn } from "@/lib/utils";

type Cmd = { id: string; label: string; group: string; icon: any; hint?: string; run: () => void | Promise<void> };

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any>(null);
  const [active, setActive] = useState(0);
  const router = useRouter();
  const { setTheme } = useTheme();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); } };
    const ev = () => setOpen(true);
    document.addEventListener("keydown", k);
    window.addEventListener("open-command-palette", ev);
    return () => { document.removeEventListener("keydown", k); window.removeEventListener("open-command-palette", ev); };
  }, []);
  useEffect(() => { if (!open) { setQ(""); setRes(null); } }, [open]);
  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    const t = setTimeout(() => api(`/search?q=${encodeURIComponent(q.trim())}`).then(setRes).catch(() => setRes(null)), 180);
    return () => clearTimeout(t);
  }, [q]);

  const go = (href: string) => () => router.push(href);
  const base: Cmd[] = useMemo(() => [
    { id: "home", label: "Go to overview", group: "Navigate", icon: LayoutDashboard, run: go("/") },
    { id: "new", label: "New analysis / upload data", group: "Navigate", icon: PlusCircle, run: go("/new") },
    { id: "datasets", label: "My datasets", group: "Navigate", icon: Database, run: go("/datasets") },
    { id: "history", label: "Analysis history", group: "Navigate", icon: History, run: go("/analyses") },
    { id: "reports", label: "Reports", group: "Navigate", icon: FileText, run: go("/reports") },
    { id: "compare", label: "Compare analyses", group: "Navigate", icon: Columns2, run: go("/compare") },
    { id: "exp", label: "Experiments", group: "Navigate", icon: Beaker, run: go("/experiments") },
    { id: "mem", label: "Learning memory", group: "Navigate", icon: BrainCircuit, run: go("/memory") },
    { id: "settings", label: "Settings", group: "Navigate", icon: Settings, run: go("/settings") },
    { id: "retail", label: "Run the retail demo", group: "Actions", icon: ShoppingCart, run: () => startDemo((h) => router.push(h), "retail") },
    { id: "churn", label: "Run the churn demo", group: "Actions", icon: Users, run: () => startDemo((h) => router.push(h), "churn", "Which customers are likely to churn?") },
    { id: "light", label: "Switch to light theme", group: "Actions", icon: Sun, run: () => setTheme("light") },
    { id: "dark", label: "Switch to dark theme", group: "Actions", icon: Moon, run: () => setTheme("dark") },
  ], [router, setTheme]); // eslint-disable-line react-hooks/exhaustive-deps

  const items: Cmd[] = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = needle ? base.filter((c) => c.label.toLowerCase().includes(needle)) : base;
    const found: Cmd[] = [];
    if (res) {
      res.datasets.forEach((d: any) => found.push({ id: d.id, label: d.name, group: "Datasets", icon: Database, run: go(`/datasets/${d.id}`) }));
      res.analyses.forEach((a: any) => found.push({ id: a.id, label: a.question, group: "Analyses", icon: History, run: go(`/analyses/${a.id}`) }));
    }
    return [...found, ...filtered];
  }, [q, res, base]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => setActive(0), [q, res]);
  useEffect(() => { listRef.current?.querySelector(`[data-idx="${active}"]`)?.scrollIntoView({ block: "nearest" }); }, [active]);

  const run = async (c?: Cmd) => { if (!c) return; setOpen(false); await c.run(); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); run(items[active]); }
  };
  let lastGroup = "";
  return (
    <D.Root open={open} onOpenChange={setOpen}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] data-[state=open]:animate-in" />
        <D.Content aria-describedby={undefined} className="fixed left-1/2 top-[14vh] z-50 w-[min(640px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-2xl border border-border bg-surface shadow-card data-[state=open]:animate-in">
          <D.Title className="sr-only">Command palette</D.Title>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search className="size-4 text-fg-3" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} placeholder="Type a command or search datasets and analyses…"
              className="h-12 flex-1 bg-transparent text-[14px] text-fg outline-none placeholder:text-fg-3" aria-label="Command" role="combobox" aria-expanded aria-controls="cmd-list"
              aria-activedescendant={items[active] ? `cmd-${items[active].id}` : undefined} />
            <kbd className="rounded border border-border px-1.5 text-[10px] text-fg-3">Esc</kbd>
          </div>
          <div ref={listRef} id="cmd-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-1.5 scrollbar-thin">
            {items.length === 0 && <div className="px-3 py-8 text-center text-[13px] text-fg-3">No matches</div>}
            {items.map((c, i) => {
              const header = c.group !== lastGroup ? (lastGroup = c.group) : null;
              return (
                <div key={c.group + c.id}>
                  {header && <div className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-fg-3">{header}</div>}
                  <button id={`cmd-${c.id}`} data-idx={i} role="option" aria-selected={i === active} onMouseMove={() => setActive(i)} onClick={() => run(c)}
                    className={cn("flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13.5px]", i === active ? "bg-accent-soft text-accent-text" : "text-fg-2")}>
                    <c.icon className="size-4 shrink-0" />
                    <span className="flex-1 truncate">{c.label}</span>
                    {i === active && <ArrowRight className="size-3.5" />}
                  </button>
                </div>
              );
            })}
          </div>
          <div className="flex gap-3 border-t border-border px-4 py-2 text-[11px] text-fg-3"><span>↑↓ to move</span><span>↵ to run</span><span>Ctrl/⌘ K to toggle</span></div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
