import { Info } from "lucide-react";
import type * as React from "react";
import { Popover, PopoverArrow, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/** The (i) button of a section whose explanation is a few lines of its own text. */
export function ReasonTip({
  label,
  title,
  children,
}: {
  label: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="inline-flex size-5 shrink-0 items-center justify-center rounded-full p-0 align-middle leading-none text-muted transition-colors hover:bg-row-hover hover:text-ink aria-expanded:bg-row-hover aria-expanded:text-ink"
        >
          <Info className="block size-[15px]" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-max max-w-[min(340px,calc(100vw-16px))] min-w-[220px] text-left [overflow-wrap:anywhere] whitespace-normal"
        aria-label={title}
      >
        <p className="m-0 text-label font-semibold">{title}</p>
        <div className="mt-1 flex flex-col gap-1.5 text-muted">{children}</div>
        <PopoverArrow />
      </PopoverContent>
    </Popover>
  );
}
