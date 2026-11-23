import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { type ClockShift, describeShift } from "./clockShifts";

/** "Earlier by 1 h 16 m, was 00:45 ET (04:45Z)": appears after an advisory moves a decide-by. Text with an arrow, not a coloured box. */
export function ShiftChip({ shift, className }: { shift: ClockShift | undefined; className?: string }) {
  if (!shift) return null;
  const { text, earlier } = describeShift(shift);
  return (
    <span
      data-testid="shift-chip"
      className={cn(
        "inline-flex items-center gap-1 rounded-sm bg-subtle px-1.5 py-0.5 text-label font-medium text-ink tnum",
        className,
      )}
    >
      <ArrowUp className={cn("size-3", !earlier && "rotate-180")} aria-hidden />
      {text}
    </span>
  );
}
