"use client";
import * as React from "react";
import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({ className, children, title, description, wide }: { className?: string; children: React.ReactNode; title: string; description?: string; wide?: boolean }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-[#05030f]/50 backdrop-blur-md fade-in" />
      <D.Content className={cn("fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-border bg-surface-solid/95 p-6 shadow-[0_40px_100px_-30px_rgba(40,20,120,0.6)] backdrop-blur-xl dialog-in max-h-[85vh] overflow-y-auto scrollbar-thin", wide ? "max-w-3xl" : "max-w-md", className)}>
        <div className="mb-4 pr-6">
          <D.Title className="text-base font-semibold text-fg">{title}</D.Title>
          {description && <D.Description className="mt-1 text-[13px] text-fg-3">{description}</D.Description>}
        </div>
        {children}
        <D.Close className="absolute right-4 top-4 rounded-md p-1 text-fg-3 hover:bg-surface-2 hover:text-fg" aria-label="Close"><X className="size-4" /></D.Close>
      </D.Content>
    </D.Portal>
  );
}
