import { ToggleGroup } from "radix-ui";
import { cn } from "@/lib/cn";

interface Segment<V extends string> {
  value: V;
  label: string;
}

interface SegmentedControlProps<V extends string> {
  value: V;
  onValueChange: (value: V) => void;
  options: readonly Segment<V>[];
  label: string;
  className?: string;
}

/** A grey track with a white thumb: two or three views of the same data: Table | Map, Now | Forecast, 12h | 24h | 48h. */
export function SegmentedControl<V extends string>({
  value,
  onValueChange,
  options,
  label,
  className,
}: SegmentedControlProps<V>) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      aria-label={label}
      onValueChange={(v) => v && onValueChange(v as V)}
      className={cn("inline-flex h-[34px] items-stretch gap-0.5 rounded-[9px] bg-surface-3 p-0.5", className)}
    >
      {options.map((o) => (
        <ToggleGroup.Item
          key={o.value}
          value={o.value}
          className="rounded-[7px] px-3.5 text-[13px] font-medium text-ink-2 transition-colors duration-120 hover:text-ink data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:ring-1 data-[state=on]:ring-hair-strong"
        >
          {o.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
