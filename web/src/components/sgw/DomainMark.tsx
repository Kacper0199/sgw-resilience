import { cn } from "@/lib/cn";

export type Domain = "power" | "water" | "docs";

const DOMAIN = {
  power: { label: "Power", fill: "bg-domain-power" },
  water: { label: "Water", fill: "bg-domain-water" },
  docs: { label: "Documents", fill: "bg-domain-docs" },
} as const;

/**
 * The 8 px rounded square for Power, Water or Documents. Used only in tags, source rows and legends: never a fill
 * or a row tint, and never carrying status. The word stays in ink; the square only repeats it.
 */
export function DomainMark({
  domain,
  withLabel = false,
  className,
}: {
  domain: Domain;
  withLabel?: boolean;
  className?: string;
}) {
  const { label, fill } = DOMAIN[domain];
  const square = cn("size-2 shrink-0 rounded-[2px]", fill);
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap", className)}>
      {withLabel ? (
        <>
          <span className={square} aria-hidden />
          <span>{label}</span>
        </>
      ) : (
        <span className={square} role="img" aria-label={label} />
      )}
    </span>
  );
}
