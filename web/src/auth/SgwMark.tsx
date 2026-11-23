import { cn } from "@/lib/cn";

/** The SGW monogram: a navy tile with the S, a gold dot for power and a teal dot for water. */
export function SgwMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" role="img" aria-label="SGW" className={cn("block shrink-0", className)}>
      <rect width="40" height="40" rx="10" className="fill-primary" />
      <text
        x="20"
        y="28.6"
        textAnchor="middle"
        fontSize="25"
        fontWeight="600"
        className="fill-on-primary font-sans"
      >
        S
      </text>
      <circle cx="31.5" cy="8.5" r="2.2" fill="#D9A21B" />
      <circle cx="31.5" cy="15.5" r="2.2" fill="#13A3B5" />
    </svg>
  );
}
