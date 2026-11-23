import { Info } from "lucide-react";
import { Tag } from "@/components/sgw";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { HazardSource } from "./hazardTypes";

export function OriginTag({ origin }: { origin: HazardSource["origin"] }) {
  return (
    <Tag data-origin={origin} data-testid="origin-tag">
      {origin === "real" ? "Real ASOS" : "Synthetic"}
    </Tag>
  );
}

/** Where every number of the view comes from: each input, real or synthetic, and its committed file. */
export function HazardInfo({ sources, asOf }: { sources: HazardSource[]; asOf: string }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Sources"
          className="inline-flex h-6 items-center gap-1 rounded px-1.5 text-[13px] font-semibold text-blue-ink hover:underline"
          data-testid="hazard-info"
        >
          <Info className="size-[15px]" aria-hidden />
          Sources
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[360px] p-0" aria-label="Sources" data-testid="hazard-sources">
        <ul className="m-0 list-none p-0">
          {sources.map((s) => (
            <li key={`${s.source}-${s.what}`} className="border-b border-hair px-4 py-2.5 last:border-b-0">
              <div className="flex items-start justify-between gap-3">
                <span className="text-[13px] leading-[18px] font-medium">{s.what}</span>
                <span className="shrink-0">
                  {s.origin === "real" ? (
                    <span className="text-[12px] font-semibold text-ink-2">Real</span>
                  ) : (
                    <span className="text-[12px] text-muted">Synthetic</span>
                  )}
                </span>
              </div>
              {s.detail && <p className="m-0 mt-0.5 text-[12px] leading-4 text-muted">{s.detail}</p>}
              <p className="m-0 mt-0.5 font-mono text-[11px] text-muted [overflow-wrap:anywhere]">
                {s.source}
              </p>
            </li>
          ))}
        </ul>
        <p className="m-0 border-t border-hair px-4 py-2 text-[12px] text-muted">
          Read-only. Values as of {asOf}, not the replay clock.
        </p>
      </PopoverContent>
    </Popover>
  );
}
