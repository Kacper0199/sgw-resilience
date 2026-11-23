import { Printer } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";

let savedTheme: string | undefined;

/**
 * Paper is always light: the reader's theme comes back after the print dialog closes. Registered once per page
 * load, not per mount, because the print layout can remount the shell between the two events.
 */
function printInLight() {
  const root = document.documentElement;
  window.addEventListener("beforeprint", () => {
    savedTheme ??= root.dataset.theme;
    root.dataset.theme = "light";
  });
  window.addEventListener("afterprint", () => {
    if (savedTheme) root.dataset.theme = savedTheme;
    savedTheme = undefined;
  });
}

if (typeof window !== "undefined") printInLight();

/** The browser's print dialog for the briefing (A4, light, no navigation); "Save as PDF" is one of its printers. */
export function PrintBrief() {
  return (
    <IconButton
      label="Print / Save as PDF"
      icon={<Printer className="size-4" aria-hidden />}
      tooltipSide="bottom"
      onClick={() => window.print()}
      data-testid="print-brief"
    />
  );
}
