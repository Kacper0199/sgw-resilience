import { Info } from "lucide-react";
import type * as React from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Popover, PopoverArrow, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { GLOSSARY, type GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";

interface InfoTipProps {
  term: GlossaryKey;
  /** Custom trigger (for example a badge). Defaults to the (i) icon button. */
  children?: React.ReactElement;
  className?: string;
  onDark?: boolean;
}

/**
 * The single toggletip. The trigger is a fixed 20x20 inline-flex target, never positioned against text.
 * The bubble wraps at 280 px, shifts or flips to stay inside the viewport, and closes on Esc, outside click,
 * scroll and resize.
 */
export function InfoTip({ term, children, className, onDark = false }: InfoTipProps) {
  const entry = GLOSSARY[term];
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {children ?? (
          <button
            type="button"
            aria-label={`What does "${entry.term}" mean?`}
            className={cn(
              "inline-flex size-5 shrink-0 items-center justify-center rounded-full p-0 align-middle leading-none transition-colors print:hidden",
              onDark
                ? "text-topbar-muted hover:bg-topbar-hover hover:text-on-topbar aria-expanded:bg-topbar-hover aria-expanded:text-on-topbar"
                : "text-muted hover:bg-row-hover hover:text-ink aria-expanded:bg-row-hover aria-expanded:text-ink",
              className,
            )}
          >
            <Info className="block size-[15px]" aria-hidden />
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent
        align="center"
        className="w-max max-w-[min(280px,calc(100vw-16px))] min-w-[200px] text-left [overflow-wrap:anywhere] whitespace-normal"
        aria-label={entry.term}
        data-testid={`infotip-${term}`}
      >
        <p className="m-0 text-label font-semibold">{entry.term}</p>
        <p className="mt-0.5 mb-1.5 text-muted">{entry.text}</p>
        <Link to={`/help#${term}`} className="text-label">
          More in Help
        </Link>
        <PopoverArrow />
      </PopoverContent>
    </Popover>
  );
}
