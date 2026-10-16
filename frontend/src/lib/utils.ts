import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtNum(v: unknown, opts: { money?: boolean; digits?: number } = {}): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v !== "number") return String(v);
  if (!Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const prefix = opts.money ? "$" : "";
  const sign = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sign}${prefix}${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${sign}${prefix}${(a / 1e3).toFixed(1)}k`;
  if (Number.isInteger(v)) return `${sign}${prefix}${a.toLocaleString()}`;
  const d = opts.digits ?? (a < 0.01 ? 4 : a < 1 ? 3 : 2);
  return `${sign}${prefix}${a.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 })}`;
}

export function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function timeAgo(iso?: string | null) {
  if (!iso) return "";
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const humanize = (s?: string | null) => (s ?? "").replace(/_/g, " ");
