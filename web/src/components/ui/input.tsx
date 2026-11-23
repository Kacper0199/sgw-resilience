import type * as React from "react";
import { cn } from "@/lib/cn";

export function Input({ className, type = "text", ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-[34px] w-full min-w-0 rounded-md border border-hair-strong bg-surface px-2.5 text-[14px] text-ink placeholder:text-faint disabled:opacity-50 aria-invalid:border-crit",
        className,
      )}
      {...props}
    />
  );
}
