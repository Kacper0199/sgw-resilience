import { X } from "lucide-react";
import { cn } from "@/lib/cn";

interface FilterChipProps {
  label: string;
  on: boolean;
  onToggle: () => void;
  /** When given and the chip is on, a × button removes the filter. */
  onRemove?: () => void;
  className?: string;
}

/** Pill toggle: blue tint and blue outline when on. */
export function FilterChip({ label, on, onToggle, onRemove, className }: FilterChipProps) {
  const removable = on && onRemove;
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center rounded-full border text-[13px] font-medium whitespace-nowrap transition-colors duration-120",
        on
          ? "border-blue-line bg-blue-soft text-blue-ink"
          : "border-hair-strong bg-surface text-ink-2 hover:bg-surface-2",
        className,
      )}
    >
      <button
        type="button"
        aria-pressed={on}
        onClick={onToggle}
        className={cn("h-full rounded-full pl-3", removable ? "pr-1" : "pr-3")}
      >
        {label}
      </button>
      {removable && (
        <button
          type="button"
          aria-label={`Remove filter ${label}`}
          onClick={onRemove}
          className="mr-1 grid size-5 place-items-center rounded-full hover:bg-blue-line/40"
        >
          <X className="size-3" aria-hidden />
        </button>
      )}
    </span>
  );
}
