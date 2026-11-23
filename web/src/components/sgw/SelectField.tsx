import { ChevronDown } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/cn";

interface SelectFieldProps extends Omit<React.ComponentProps<"select">, "children"> {
  /** Shown inside the field: "Utility" renders "Utility: All". */
  label: string;
  options: readonly { value: string; label: string }[];
}

/** Outline field with its label inside. A native select, so the keyboard and screen readers behave. */
export function SelectField({ label, options, className, ...props }: SelectFieldProps) {
  return (
    <label
      className={cn(
        "relative inline-flex h-[34px] items-center gap-1 rounded-md border border-hair-strong bg-surface pr-8 pl-3 text-[13px] text-muted focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-blue hover:bg-surface-2",
        className,
      )}
    >
      <span aria-hidden>{label}:</span>
      <select
        aria-label={label}
        className="h-full cursor-pointer appearance-none bg-transparent pr-1 font-medium text-ink outline-none"
        {...props}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 size-4 text-muted" aria-hidden />
    </label>
  );
}
