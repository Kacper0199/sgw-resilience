import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { Slot } from "radix-ui";
import type * as React from "react";
import { cn } from "@/lib/cn";

const secondary = "border-[1.5px] border-blue bg-surface text-blue-ink hover:bg-blue-soft";
const tertiary = "text-blue-ink hover:underline";

export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-[13px] font-semibold transition-colors duration-120 disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-primary text-on-primary hover:bg-primary-hover",
        secondary,
        outline: secondary,
        tertiary,
        link: tertiary,
        ghost: "text-ink hover:bg-surface-2",
        destructive: "border-[1.5px] border-crit bg-surface text-crit hover:bg-crit-soft",
        "destructive-solid": "bg-crit text-on-crit hover:opacity-90",
      },
      size: {
        default: "h-[34px] px-4",
        sm: "h-7 rounded-[7px] px-3 text-xs",
        icon: "size-[34px] rounded-md",
        "icon-sm": "size-7 rounded-[7px]",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);

export interface ButtonProps extends React.ComponentProps<"button">, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Shows a spinner, sets aria-busy and blocks clicks. */
  loading?: boolean;
}

export function Button({
  className,
  variant,
  size,
  asChild = false,
  loading = false,
  type,
  disabled,
  children,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      data-slot="button"
      type={asChild ? undefined : (type ?? "button")}
      aria-busy={loading || undefined}
      disabled={asChild ? undefined : disabled || loading}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    >
      {asChild ? (
        children
      ) : (
        <>
          {loading && <Loader2 className="sgw-spin" aria-hidden />}
          {children}
        </>
      )}
    </Comp>
  );
}
