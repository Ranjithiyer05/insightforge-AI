import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn("h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-fg placeholder:text-fg-3 shadow-xs outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60", className)} {...p} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn("w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-fg placeholder:text-fg-3 shadow-xs outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 resize-none", className)} {...p} />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...p }, ref) => (
  <select ref={ref} className={cn("h-9 w-full rounded-lg border border-border bg-surface px-2.5 text-sm text-fg shadow-xs outline-none focus:border-accent focus:ring-2 focus:ring-accent/20", className)} {...p} />
));
Select.displayName = "Select";

export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-[12.5px] font-medium text-fg-2", className)} {...p} />;
}
