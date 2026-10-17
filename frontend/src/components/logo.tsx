import { cn } from "@/lib/utils";

/** InsightForge mark: three rising bars with a spark, in a gradient tile. */
export function LogoMark({ className, size = 36 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className={cn("shrink-0", className)} aria-hidden="true">
      <defs>
        <linearGradient id="if-bg" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="#7c6cff" /><stop offset="0.55" stopColor="#5046e5" /><stop offset="1" stopColor="#2f2a9e" />
        </linearGradient>
        <linearGradient id="if-bar" x1="0" y1="30" x2="0" y2="10" gradientUnits="userSpaceOnUse">
          <stop stopColor="#ffffff" stopOpacity="0.75" /><stop offset="1" stopColor="#ffffff" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill="url(#if-bg)" />
      <rect x="0.5" y="0.5" width="39" height="39" rx="10.5" fill="none" stroke="#fff" strokeOpacity="0.18" />
      <rect x="9" y="21" width="5" height="10" rx="2" fill="url(#if-bar)" />
      <rect x="17.5" y="16" width="5" height="15" rx="2" fill="url(#if-bar)" />
      <rect x="26" y="11" width="5" height="20" rx="2" fill="url(#if-bar)" />
      <path d="M31.5 4.5l1.1 2.6 2.6 1.1-2.6 1.1-1.1 2.6-1.1-2.6-2.6-1.1 2.6-1.1z" fill="#c4f1ff" />
    </svg>
  );
}

export function Logo({ collapsed, tagline = true, className, dark }: { collapsed?: boolean; tagline?: boolean; className?: string; dark?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark size={34} className="drop-shadow-[0_4px_12px_rgba(80,70,229,0.45)]" />
      {!collapsed && (
        <div className="leading-tight">
          <div className={cn("text-[15px] font-semibold tracking-tight", dark ? "text-white" : "text-fg")}>Insight<span className={dark ? "grad-text" : "text-accent-text dark:grad-text"}>Forge</span></div>
          {tagline && <div className={cn("text-[11px]", dark ? "text-white/50" : "text-fg-3")}>Autonomous data scientist</div>}
        </div>
      )}
    </div>
  );
}
