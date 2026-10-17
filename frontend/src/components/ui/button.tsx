import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-fg text-bg shadow-xs hover:bg-fg/85",
        secondary: "bg-surface border border-border text-fg hover:bg-surface-2 shadow-xs",
        ghost: "text-fg-2 hover:bg-surface-2 hover:text-fg",
        danger: "bg-danger text-white hover:opacity-90",
        white: "bg-white text-[#111110] hover:bg-white/90",
        accent: "bg-accent text-white shadow-[0_1px_0_rgba(255,255,255,0.25)_inset,0_6px_16px_-8px_var(--accent)] hover:bg-accent-hover",
        soft: "bg-accent-soft text-accent-text hover:brightness-95",
        link: "text-accent-text underline-offset-4 hover:underline px-0",
      },
      size: { default: "h-9 px-3.5", sm: "h-8 px-2.5 text-[13px]", lg: "h-10 px-5", icon: "h-9 w-9", "icon-sm": "h-8 w-8" },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
});
Button.displayName = "Button";
export { buttonVariants };
