import { ChevronRight } from "lucide-react";
import type * as React from "react";
import { useId, useState } from "react";
import { cn } from "@/lib/cn";

interface ExpandableRowProps {
  /** Table cells after the chevron cell. */
  children: React.ReactNode;
  /** Full-width detail shown under the row when open. */
  detail: React.ReactNode;
  /** Number of columns including the chevron cell. */
  colSpan: number;
  /** Accessible name for the toggle, for example "Cedarfall". */
  label: string;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}

/** A row with a chevron cell; click or Enter toggles a full-width detail row on the selected tint with a blue edge. Open when abnormal. */
export function ExpandableRow({
  children,
  detail,
  colSpan,
  label,
  open: controlled,
  defaultOpen = false,
  onOpenChange,
  className,
}: ExpandableRowProps) {
  const [inner, setInner] = useState(defaultOpen);
  const open = controlled ?? inner;
  const panelId = useId();
  const toggle = () => {
    const next = !open;
    setInner(next);
    onOpenChange?.(next);
  };
  return (
    <>
      <tr
        data-row=""
        data-expanded={open}
        onClick={(e) => {
          if (!(e.target as Element).closest("a,button,input,select,[role=dialog]")) toggle();
        }}
        className={cn(
          "h-11 cursor-pointer border-b border-hair hover:bg-surface-2",
          open && "bg-selected hover:bg-selected [&>td:first-child]:shadow-[inset_3px_0_0_var(--blue)]",
          className,
        )}
      >
        <td className="w-9 pl-3">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
            onClick={toggle}
            className="grid size-6 place-items-center rounded text-muted hover:text-ink"
          >
            <ChevronRight
              className={cn("size-4 transition-transform duration-[160ms]", open && "rotate-90")}
              aria-hidden
            />
          </button>
        </td>
        {children}
      </tr>
      {open && (
        <tr id={panelId} className="border-b border-hair bg-selected/40 shadow-[inset_3px_0_0_var(--blue)]">
          <td colSpan={colSpan} className="px-12 py-4">
            {detail}
          </td>
        </tr>
      )}
    </>
  );
}
