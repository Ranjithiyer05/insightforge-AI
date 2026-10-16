"use client";
import * as React from "react";
import * as T from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface-2", className)} />;
}

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items, className }: { value: T; onChange: (v: T) => void; items: { value: T; label: React.ReactNode; count?: number }[]; className?: string }) {
  return (
    <div role="tablist" className={cn("inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-xl bg-surface-2/80 p-1 ring-1 ring-inset ring-border", className)}>
      {items.map((it) => (
        <button key={it.value} role="tab" aria-selected={value === it.value} onClick={() => onChange(it.value)}
          className={cn("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium whitespace-nowrap transition", value === it.value ? "bg-surface text-fg shadow-card ring-1 ring-border" : "text-fg-3 hover:text-fg")}>
          {it.label}
          {it.count !== undefined && <span className="rounded bg-surface-3 px-1 text-[11px] num text-fg-3">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <T.Provider delayDuration={200}>
      <T.Root>
        <T.Trigger asChild>{children}</T.Trigger>
        <T.Portal>
          <T.Content sideOffset={6} className="z-50 max-w-xs rounded-md bg-fg px-2 py-1 text-xs text-bg shadow-card animate-in">{content}</T.Content>
        </T.Portal>
      </T.Root>
    </T.Provider>
  );
}

export function EmptyState({ icon: Icon, title, description, action }: { icon: React.ComponentType<{ className?: string }>; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong px-6 py-12 text-center">
      <div className="mb-3 flex size-10 items-center justify-center rounded-lg bg-accent-soft text-accent-text"><Icon className="size-5" /></div>
      <p className="text-sm font-semibold text-fg">{title}</p>
      {description && <p className="mt-1 max-w-sm text-[13px] text-fg-3">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[14px] text-fg-3">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return <div className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger">{message}</div>;
}
