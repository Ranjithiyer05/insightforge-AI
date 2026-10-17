"use client";
import * as React from "react";
import * as M from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

export const Dropdown = M.Root;
export const DropdownTrigger = M.Trigger;
export function DropdownContent({ className, ...p }: M.DropdownMenuContentProps) {
  return (
    <M.Portal>
      <M.Content sideOffset={6} align="end" className={cn("z-50 min-w-48 rounded-xl border border-border bg-surface-solid/95 p-1.5 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.35)] backdrop-blur-xl pop-in", className)} {...p} />
    </M.Portal>
  );
}
export function DropdownItem({ className, ...p }: M.DropdownMenuItemProps) {
  return <M.Item className={cn("flex cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm transition-colors text-fg-2 outline-none data-[highlighted]:bg-surface-2 data-[highlighted]:text-fg [&_svg]:size-4", className)} {...p} />;
}
export function DropdownLabel({ className, ...p }: M.DropdownMenuLabelProps) {
  return <M.Label className={cn("px-2 py-1.5 text-xs text-fg-3", className)} {...p} />;
}
export const DropdownSeparator = () => <M.Separator className="my-1 h-px bg-border" />;
