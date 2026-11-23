import { FileText, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";

interface SourceBadgeProps {
  n: number;
  citationId: string;
  unverified?: boolean;
  active?: boolean;
  onSelect: (n: number) => void;
}

/** The inline source pill after a sentence: document icon and short name. A real button; it selects its row in Sources. */
export function SourceBadge({
  n,
  citationId,
  unverified = false,
  active = false,
  onSelect,
}: SourceBadgeProps) {
  const Icon = unverified ? TriangleAlert : FileText;
  return (
    <button
      type="button"
      onClick={() => onSelect(n)}
      aria-label={`Source ${n}: ${citationId}${unverified ? ", unverified" : ""}`}
      aria-pressed={active}
      data-testid="source-badge"
      className={cn(
        "mx-0.5 inline-flex h-6 items-center gap-1 rounded-sm px-1.5 align-middle text-[12px] font-medium whitespace-nowrap transition-colors duration-120",
        active
          ? "bg-blue-line text-blue-ink ring-1 ring-blue ring-inset"
          : "bg-blue-soft text-blue-ink hover:bg-blue-line",
        unverified && "text-warn",
      )}
    >
      <Icon aria-hidden className="size-3 shrink-0" />
      <span className="font-mono text-[11.5px]">{citationId}</span>
    </button>
  );
}
