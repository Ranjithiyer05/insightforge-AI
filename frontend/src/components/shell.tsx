"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import {
  BarChart3, Beaker, BrainCircuit, ChevronsLeft, ChevronsRight, Database, FileText, History, LayoutDashboard, LogOut, Menu, Moon,
  PlusCircle, Columns2, Search, Settings, Shield, Sun, Monitor, Cpu, Sparkles, X, FolderKanban, LayoutGrid,
} from "lucide-react";
import { Logo } from "./logo";
import { motion } from "./motion";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { isPublicRoute, useAuth } from "./auth";
import { useWorkspace } from "./workspace";
import { Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownSeparator, DropdownTrigger } from "./ui/dropdown";
import { Tooltip } from "./ui/misc";
import { CommandPalette } from "./command-palette";
import { PageTransition } from "./motion";

const NAV_GROUPS = [
  { label: "Workspace", items: [
    { href: "/", label: "Overview", icon: LayoutDashboard },
    { href: "/new", label: "New Analysis", icon: PlusCircle },
    { href: "/datasets", label: "My Datasets", icon: Database },
    { href: "/analyses", label: "Analysis History", icon: History },
    { href: "/reports", label: "Reports", icon: FileText },
    { href: "/dashboards", label: "Dashboards", icon: LayoutGrid },
    { href: "/compare", label: "Compare", icon: Columns2 },
  ] },
  { label: "Learning", items: [
    { href: "/experiments", label: "Experiments", icon: Beaker },
    { href: "/memory", label: "Learning Memory", icon: BrainCircuit },
  ] },
  { label: "System", items: [{ href: "/settings", label: "Settings", icon: Settings }] },
];

function Sidebar({ collapsed, onToggle, mobile, onClose }: { collapsed: boolean; onToggle: () => void; mobile?: boolean; onClose?: () => void }) {
  const path = usePathname();
  const { user } = useAuth();
  const groups = user?.is_admin
    ? NAV_GROUPS.map((g) => (g.label === "System" ? { ...g, items: [...g.items, { href: "/admin", label: "Admin", icon: Shield }] } : g))
    : NAV_GROUPS;
  return (
    <aside className={cn("sidebar relative flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--sb-border)] shadow-xs transition-[width] duration-300 ease-[cubic-bezier(.22,1,.36,1)] motion-reduce:transition-none", collapsed ? "w-[72px]" : "w-[248px]")}>
      <div className="flex h-16 items-center justify-between px-4">
        <Link href="/" className="px-1"><Logo collapsed={collapsed} /></Link>
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
                    className={cn("group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] font-medium transition-colors",
                      active ? "text-[var(--sb-text-strong)]" : "text-[var(--sb-text)] hover:bg-[var(--sb-hover)] hover:text-[var(--sb-text-strong)]", collapsed && "justify-center px-0")}>
                    {active && <motion.span layoutId="nav-active" className="absolute inset-0 -z-0 rounded-[inherit] border border-[var(--sb-border)] shadow-xs" style={{ background: "var(--sb-active)" }} transition={{ type: "spring", stiffness: 480, damping: 38 }} />}
                    <it.icon className={cn("relative size-[18px] shrink-0", active ? "text-accent" : "text-[var(--sb-text-3)] group-hover:text-[var(--sb-text-strong)]")} />
                    {!collapsed && <span className="relative">{it.label}</span>}
                  </Link>
                );
                return collapsed ? <Tooltip key={it.href} content={it.label}>{link}</Tooltip> : link;
              })}
            </div>
          </div>
        ))}
      </nav>
      {!collapsed && (
        <div className="mx-3 mb-3 rounded-xl border border-[var(--sb-border)] bg-[var(--sb-hover)] p-3">
          <div className="flex items-center gap-2 text-[12px] font-medium text-[var(--sb-text-strong)]"><Shield className="size-3.5 text-accent" /> Verified by default</div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--sb-text-3)]">Every key number is recomputed from your raw data before it is shown.</p>
        </div>
      )}
      {!mobile && (
        <div className="border-t border-[var(--sb-border)] p-2">
          <button onClick={onToggle} className={cn("flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] text-[var(--sb-text-3)] hover:bg-[var(--sb-hover)] hover:text-[var(--sb-text-strong)]", collapsed && "justify-center")} aria-label="Toggle sidebar">
            {collapsed ? <ChevronsRight className="size-4" /> : <><ChevronsLeft className="size-4" /> Collapse</>}
          </button>
        </div>
      )}
    </aside>
  );
}

function GlobalSearch() {
  return (
    <button onClick={() => window.dispatchEvent(new Event("open-command-palette"))}
      className="group hidden h-9 w-full max-w-md items-center gap-2 rounded-xl border border-border bg-surface-2 px-3 text-[13px] text-fg-3 transition hover:border-border-strong hover:text-fg-2 md:flex" aria-label="Open command palette">
      <Search className="size-4" /> <span className="flex-1 text-left">Search or jump to…</span>
      <kbd className="rounded border border-border bg-surface px-1 text-[10px]">Ctrl K</kbd>
    </button>
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

function GuestNotice() {
  const { user } = useAuth();
  if (!user?.is_guest) return null;
  return (
    <div role="status" className="mx-3 mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-accent/20 bg-accent-soft px-4 py-2 backdrop-blur lg:ml-0 text-[12.5px] text-accent-text sm:px-6">
      You are exploring as a guest. This account and its data are deleted automatically within a day.
      <Link href="/register" className="font-medium underline underline-offset-2">Create an account</Link> to keep your work.
    </div>
  );
}

function StorageNotice() {
  const { data } = useApi<any>("/health");
  const [hidden, setHidden] = useState(false);
  if (!data || data.storage?.persistent !== false || hidden) return null;
  return (
    <div role="status" className="mx-3 mt-2 flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-soft px-4 py-2 backdrop-blur lg:ml-0 text-[12.5px] text-warning sm:px-6">
      <span className="flex-1">{data.storage.message}</span>
      <button onClick={() => setHidden(true)} className="rounded p-0.5 hover:bg-warning/10" aria-label="Dismiss notice"><X className="size-3.5" /></button>
    </div>
  );
}

function Topbar({ onMenu }: { onMenu: () => void }) {
  const { user, logout } = useAuth();
  const { current } = useWorkspace();
  return (
    <header className="relative z-30 bg-surface mx-3 mt-3 flex h-14 items-center gap-3 rounded-2xl border border-border px-3 shadow-[inset_0_1px_0_var(--card-hi),var(--shadow)] sm:px-4 lg:ml-0">
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
        <DropdownTrigger className="flex size-8 items-center justify-center rounded-full bg-accent text-[12px] font-semibold text-white ring-2 ring-surface shadow-xs" aria-label="Profile menu">
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

/** Moves the hover spotlight on cards to follow the pointer. */
function spotlight(e: React.PointerEvent) {
  const el = (e.target as HTMLElement).closest?.(".card-surface") as HTMLElement | null;
  if (!el) return;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--mx", `${e.clientX - r.left}px`);
  el.style.setProperty("--my", `${e.clientY - r.top}px`);
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
    <div className="app-bg relative flex h-screen overflow-hidden" onPointerMove={spotlight}>
      <div className="aurora" aria-hidden="true"></div>
      <div className="relative z-10 hidden p-3 lg:block"><Sidebar collapsed={collapsed} onToggle={() => { setCollapsed(!collapsed); try { localStorage.setItem("if-sidebar", collapsed ? "0" : "1"); } catch {} }} /></div>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-[#05030f]/50 backdrop-blur-sm fade-in" onClick={() => setMobileOpen(false)} />
          <div className="relative h-full w-[264px] p-2 animate-in"><Sidebar collapsed={false} onToggle={() => {}} mobile onClose={() => setMobileOpen(false)} /></div>
        </div>
      )}
      <CommandPalette />
      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setMobileOpen(true)} />
        <GuestNotice />
        <StorageNotice />
        <main className="flex-1 overflow-y-auto scrollbar-thin">
          <div className="mx-auto w-full max-w-[1360px] px-4 py-7 sm:px-6 lg:px-8"><PageTransition id={path}>{children}</PageTransition></div>
        </main>
      </div>
    </div>
  );
}
