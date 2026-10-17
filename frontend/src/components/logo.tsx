import { cn } from "@/lib/utils";

/** InsightForge mark: three rising bars and a spark on a solid tile. Colours follow the theme. */
export function LogoMark({ className, size = 36 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className={cn("shrink-0", className)} aria-hidden="true">
      <rect width="40" height="40" rx="10" fill="var(--logo-bg)" />
      <rect x="9" y="21" width="5" height="10" rx="1.5" fill="var(--logo-fg)" opacity="0.55" />
      <rect x="17.5" y="16" width="5" height="15" rx="1.5" fill="var(--logo-fg)" opacity="0.8" />
      <rect x="26" y="11" width="5" height="20" rx="1.5" fill="var(--logo-fg)" />
      <circle cx="31.5" cy="7" r="3" fill="var(--accent)" />
    </svg>
  );
}

export function Logo({ collapsed, tagline = true, className, dark }: { collapsed?: boolean; tagline?: boolean; className?: string; dark?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark size={32} />
      {!collapsed && (
        <div className="leading-tight">
          <div className={cn("font-display text-[15px] font-semibold tracking-tight", dark ? "text-white" : "text-fg")}>InsightForge</div>
          {tagline && <div className={cn("text-[11px]", dark ? "text-white/50" : "text-fg-3")}>Autonomous data scientist</div>}
        </div>
      )}
    </div>
  );
}
