"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import {
  BarChart3, Beaker, BrainCircuit, ChevronsLeft, ChevronsRight, Database, FileText, History, LayoutDashboard, LogOut, Menu, Moon,
  PlusCircle, Columns2, Search, Settings, Shield, Sun, Monitor, Cpu, Sparkles, X, FolderKanban,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { isPublicRoute, useAuth } from "./auth";
import { useWorkspace } from "./workspace";
import { Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownSeparator, DropdownTrigger } from "./ui/dropdown";
import { Tooltip } from "./ui/misc";

const NAV_GROUPS = [
  { label: "Workspace", items: [
    { href: "/", label: "Overview", icon: LayoutDashboard },
    { href: "/new", label: "New Analysis", icon: PlusCircle },
    { href: "/datasets", label: "My Datasets", icon: Database },
    { href: "/analyses", label: "Analysis History", icon: History },
    { href: "/reports", label: "Reports", icon: FileText },
    { href: "/compare", label: "Compare", icon: Columns2 },
  ] },
  { label: "Learning", items: [
    { href: "/experiments", label: "Experiments", icon: Beaker },
    { href: "/memory", label: "Learning Memory", icon: BrainCircuit },
  ] },
  { label: "System", items: [{ href: "/settings", label: "Settings", icon: Settings }] },
];

function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-1">
      <div className="relative flex size-9 items-center justify-center rounded-xl grad-accent text-white shadow-[0_6px_20px_-6px_rgba(139,92,246,0.8)]">
        <Sparkles className="size-[18px]" />
      </div>
      {!collapsed && <div className="leading-tight"><div className="text-[15px] font-semibold tracking-tight text-white">InsightForge</div><div className="text-[11px] text-[var(--sb-text-3)]">Autonomous data scientist</div></div>}
    </Link>
  );
}

function Sidebar({ collapsed, onToggle, mobile, onClose }: { collapsed: boolean; onToggle: () => void; mobile?: boolean; onClose?: () => void }) {
  const path = usePathname();
  const { user } = useAuth();
  const groups = user?.is_admin
    ? NAV_GROUPS.map((g) => (g.label === "System" ? { ...g, items: [...g.items, { href: "/admin", label: "Admin", icon: Shield }] } : g))
    : NAV_GROUPS;
  return (
    <aside className={cn("sidebar flex h-full flex-col border-r border-[var(--sb-border)] transition-[width] duration-200", collapsed ? "w-[72px]" : "w-64")}>
      <div className="flex h-16 items-center justify-between px-4">
        <Logo collapsed={collapsed} />
        {mobile && <button onClick={onClose} className="rounded-md p-1.5 text-[var(--sb-text-3)] hover:bg-[var(--sb-hover)]" aria-label="Close menu"><X className="size-4" /></button>}
      </div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-3 scrollbar-thin">
        {groups.map((g) => (
          <div key={g.label}>
            {!collapsed && <div className="mb-1.5 px-2.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-[var(--sb-text-3)]">{g.label}</div>}
            <div className="space-y-0.5">
              {g.items.map((it) => {
                const active = it.href === "/" ? path === "/" : path.startsWith(it.href);
                const link = (
                  <Link key={it.href} href={it.href} onClick={onClose}
                    className={cn("group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors",
                      active ? "bg-[var(--sb-active)] text-white" : "text-[var(--sb-text)] hover:bg-[var(--sb-hover)] hover:text-white", collapsed && "justify-center px-0")}>
                    {active && <span className="absolute -left-3 top-1.5 bottom-1.5 w-[3px] rounded-r-full grad-accent" />}
                    <it.icon className={cn("size-[18px] shrink-0", active ? "text-[#b4adff]" : "text-[var(--sb-text-3)] group-hover:text-white")} />
                    {!collapsed && it.label}
                  </Link>
                );
                return collapsed ? <Tooltip key={it.href} content={it.label}>{link}</Tooltip> : link;
              })}
            </div>
          </div>
        ))}
      </nav>
      {!collapsed && (
        <div className="mx-3 mb-3 rounded-xl border border-[var(--sb-border)] bg-white/[0.04] p-3">
          <div className="flex items-center gap-2 text-[12px] font-medium text-white"><Shield className="size-3.5 text-[#67e8f9]" /> Verified by default</div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--sb-text-3)]">Every key number is recomputed from your raw data before it is shown.</p>
        </div>
      )}
      {!mobile && (
        <div className="border-t border-[var(--sb-border)] p-2">
          <button onClick={onToggle} className={cn("flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] text-[var(--sb-text-3)] hover:bg-[var(--sb-hover)] hover:text-white", collapsed && "justify-center")} aria-label="Toggle sidebar">
            {collapsed ? <ChevronsRight className="size-4" /> : <><ChevronsLeft className="size-4" /> Collapse</>}
          </button>
        </div>
      )}
    </aside>
  );
}

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any>(null);
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    const t = setTimeout(() => api(`/search?q=${encodeURIComponent(q.trim())}`).then(setRes).catch(() => {}), 220);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); ref.current?.querySelector("input")?.focus(); } };
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); document.removeEventListener("keydown", k); };
  }, []);
  const go = (href: string) => { setOpen(false); setQ(""); router.push(href); };
  const total = res ? res.datasets.length + res.analyses.length + res.lessons.length + res.projects.length : 0;
  return (
    <div ref={ref} className="relative hidden w-full max-w-sm md:block">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-3" />
      <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} placeholder="Search datasets, analyses, lessons…"
        className="h-9 w-full rounded-xl border border-border bg-surface-2/70 pl-8 pr-12 text-[13px] text-fg placeholder:text-fg-3 outline-none focus:border-accent focus:bg-surface" aria-label="Global search" />
      <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-border bg-surface px-1 text-[10px] text-fg-3">⌘K</kbd>
      {open && res && (
        <div className="absolute left-0 right-0 top-10 z-50 max-h-96 overflow-auto rounded-lg border border-border bg-surface p-1 shadow-card scrollbar-thin">
          {total === 0 && <div className="px-3 py-4 text-center text-[13px] text-fg-3">No matches</div>}
          {[["Projects", res.projects, (p: any) => [p.name, `/?project=${p.id}`]], ["Datasets", res.datasets, (d: any) => [d.name, `/datasets/${d.id}`]],
            ["Analyses", res.analyses, (a: any) => [a.question, `/analyses/${a.id}`]], ["Lessons", res.lessons, (l: any) => [l.statement, `/memory?lesson=${l.id}`]]]
            .filter(([, items]: any) => items.length).map(([label, items, f]: any) => (
              <div key={label}>
                <div className="px-2 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-fg-3">{label}</div>
                {items.map((it: any) => { const [t, href] = f(it); return <button key={it.id} onClick={() => go(href)} className="block w-full truncate rounded-md px-2 py-1.5 text-left text-[13px] text-fg-2 hover:bg-surface-2 hover:text-fg">{t}</button>; })}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const Icon = !mounted ? Sun : theme === "dark" ? Moon : theme === "system" ? Monitor : Sun;
  return (
    <Dropdown>
      <DropdownTrigger className="flex size-8 items-center justify-center rounded-lg text-fg-3 hover:bg-surface-2 hover:text-fg" aria-label="Theme"><Icon className="size-4" /></DropdownTrigger>
      <DropdownContent className="min-w-36">
        <DropdownItem onSelect={() => setTheme("light")}><Sun /> Light</DropdownItem>
        <DropdownItem onSelect={() => setTheme("dark")}><Moon /> Dark</DropdownItem>
        <DropdownItem onSelect={() => setTheme("system")}><Monitor /> System</DropdownItem>
      </DropdownContent>
    </Dropdown>
  );
}

function ExecStatus() {
  const { data } = useApi<any>("/status", { poll: () => true, interval: 5000 });
  if (!data) return null;
  const running = data.running_analyses + data.running_evaluations;
  return (
    <Tooltip content={<div className="space-y-0.5"><div>{running ? `${running} job(s) running` : "No jobs running"}</div><div>LLM: {data.llm.configured ? `${data.llm.provider} (${data.llm.model})` : "not configured (deterministic mode)"}</div><div>Sandbox network isolation: {data.sandbox.network_isolation ? "on" : "unavailable"}</div></div>}>
      <div className="hidden items-center gap-2 rounded-lg border border-border px-2.5 py-1 text-[12px] text-fg-2 sm:flex">
        <span className={cn("size-2 rounded-full", running ? "bg-info pulse-dot" : "bg-success")} />
        {running ? `${running} running` : "Idle"}
        <span className="text-border-strong">|</span>
        <Cpu className="size-3.5 text-fg-3" />
        {data.llm.configured ? data.llm.provider : "Deterministic"}
      </div>
    </Tooltip>
  );
}

function StorageNotice() {
  const { data } = useApi<any>("/health");
  const [hidden, setHidden] = useState(false);
  if (!data || data.storage?.persistent !== false || hidden) return null;
  return (
    <div role="status" className="flex items-start gap-2 border-b border-warning/30 bg-warning-soft px-4 py-2 text-[12.5px] text-warning sm:px-6">
      <span className="flex-1">{data.storage.message}</span>
      <button onClick={() => setHidden(true)} className="rounded p-0.5 hover:bg-warning/10" aria-label="Dismiss notice"><X className="size-3.5" /></button>
    </div>
  );
}

function Topbar({ onMenu }: { onMenu: () => void }) {
  const { user, logout } = useAuth();
  const { current } = useWorkspace();
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border/70 bg-surface/70 px-4 backdrop-blur-xl sm:px-6">
      <button onClick={onMenu} className="rounded-md p-1.5 text-fg-3 hover:bg-surface-2 lg:hidden" aria-label="Open menu"><Menu className="size-5" /></button>
      <div className="flex min-w-0 items-center gap-1.5 text-[13px]">
        <FolderKanban className="size-4 shrink-0 text-fg-3" />
        <span className="truncate font-medium text-fg">{current.projectName || "No project"}</span>
        {current.datasetName && <><span className="text-fg-3">/</span><Link href={`/datasets/${current.datasetId}`} className="truncate text-fg-2 hover:text-fg">{current.datasetName}</Link></>}
      </div>
      <div className="flex flex-1 justify-center px-2"><GlobalSearch /></div>
      <ExecStatus />
      <ThemeSwitch />
      <Dropdown>
        <DropdownTrigger className="flex size-8 items-center justify-center rounded-full grad-accent text-[12px] font-semibold text-white ring-2 ring-surface shadow-xs" aria-label="Profile menu">
          {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
        </DropdownTrigger>
        <DropdownContent>
          <DropdownLabel><div className="font-medium text-fg">{user?.name}</div><div>{user?.email}</div></DropdownLabel>
          <DropdownSeparator />
          <DropdownItem asChild><Link href="/settings"><Settings /> Settings</Link></DropdownItem>
          {user?.is_admin && <DropdownItem asChild><Link href="/admin"><Shield /> Admin</Link></DropdownItem>}
          <DropdownItem onSelect={logout}><LogOut /> Sign out</DropdownItem>
        </DropdownContent>
      </Dropdown>
    </header>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { user, loading } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => { try { setCollapsed(localStorage.getItem("if-sidebar") === "1"); } catch {} }, []);
  if (isPublicRoute(path)) return <>{children}</>;
  if (loading || !user) {
    return <div className="flex h-screen items-center justify-center text-sm text-fg-3"><BarChart3 className="mr-2 size-4 animate-pulse" /> Loading workspace…</div>;
  }
  return (
    <div className="flex h-screen overflow-hidden">
      <div className="hidden lg:block"><Sidebar collapsed={collapsed} onToggle={() => { setCollapsed(!collapsed); try { localStorage.setItem("if-sidebar", collapsed ? "0" : "1"); } catch {} }} /></div>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMobileOpen(false)} />
          <div className="relative h-full w-64 animate-in"><Sidebar collapsed={false} onToggle={() => {}} mobile onClose={() => setMobileOpen(false)} /></div>
        </div>
      )}
      <div className="app-bg flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setMobileOpen(true)} />
        <StorageNotice />
        <main className="flex-1 overflow-y-auto scrollbar-thin">
          <div className="mx-auto w-full max-w-[1320px] px-4 py-7 sm:px-6 lg:px-10">{children}</div>
        </main>
      </div>
    </div>
  );
}
