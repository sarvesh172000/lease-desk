"use client";

import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip } from "./Tooltip";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "quiet";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-ink hover:bg-accent-strong shadow-raised " +
    "hover:shadow-glow active:translate-y-px",
  secondary:
    "bg-raised text-ink border border-line hover:border-line-strong hover:bg-surface",
  ghost: "text-ink-soft hover:text-ink hover:bg-raised",
  danger: "bg-bad/10 text-bad border border-bad-line hover:bg-bad/20",
  quiet: "text-ink-muted hover:text-ink",
};

const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-xs",
  md: "h-10 px-4 text-sm gap-2 rounded-sm",
  lg: "h-12 px-6 text-base gap-2.5 rounded-md",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  /**
   * Why the button is disabled. A disabled control with no explanation is the
   * commonest way a UI wastes somebody's time — this one says so on hover.
   */
  disabledReason?: string;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, disabledReason, icon, className,
    children, disabled, type = "button", ...rest },
  ref,
) {
  const isDisabled = disabled || loading || Boolean(disabledReason);

  const button = (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex select-none items-center justify-center font-medium",
        "transition-all duration-fast ease-out",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none",
        "disabled:hover:translate-y-0 disabled:hover:bg-inherit",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );

  return disabledReason ? (
    <Tooltip label={disabledReason}>
      <span className="inline-flex">{button}</span>
    </Tooltip>
  ) : (
    button
  );
});
