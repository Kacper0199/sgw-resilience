import type * as React from "react";
import { cn } from "@/lib/cn";

export function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "min-h-16 w-full rounded-md border border-hair-strong bg-surface px-2.5 py-1.5 text-[14px] text-ink placeholder:text-faint aria-invalid:border-crit",
        className,
      )}
      {...props}
    />
  );
}
