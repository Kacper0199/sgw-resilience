import { Moon, Search, Sun } from "lucide-react";
import { PersonaMenu } from "./PersonaMenu";
import { ScenarioClock } from "./ScenarioClock";
import { ScenarioMenu } from "./ScenarioMenu";
import { useTheme } from "./useTheme";

/** Dark navy band, not frosted: product, search, clock, the one scenario menu, theme and person. */
export function TopBand({ onOpenPalette }: { onOpenPalette: () => void }) {
  const [theme, toggleTheme] = useTheme();
  return (
    <header
      className="print:hidden band flex h-14 shrink-0 items-center gap-2.5 border-b border-topbar-border bg-topbar px-4 text-on-topbar max-[819px]:h-auto max-[819px]:flex-wrap max-[819px]:gap-x-2 max-[819px]:gap-y-1.5 max-[819px]:px-3 max-[819px]:py-1.5"
      data-testid="top-band"
    >
      <div className="mr-1 text-[15px] font-bold tracking-tight whitespace-nowrap">
        SGW <span className="font-normal text-topbar-muted max-[819px]:hidden">Resilience</span>
      </div>
      <button
        type="button"
        onClick={onOpenPalette}
        className="inline-flex h-[34px] min-w-11 flex-[0_1_280px] items-center gap-2 rounded-lg border border-topbar-line px-2.5 text-[13px] hover:bg-topbar-hover max-[1429px]:w-[34px] max-[1429px]:min-w-0 max-[1429px]:flex-none max-[1429px]:justify-center max-[1429px]:px-0"
      >
        <Search className="size-4 shrink-0 text-topbar-muted" aria-hidden />
        <span className="flex-1 truncate text-left text-topbar-muted max-[1429px]:sr-only">
          Search decisions and pages
        </span>
        <kbd className="rounded border border-topbar-line px-1 font-mono text-[11px] leading-4 text-topbar-muted max-[1429px]:hidden">
          ⌘K
        </kbd>
      </button>
      <div className="ml-auto inline-flex items-center max-[819px]:ml-0">
        <ScenarioClock />
      </div>
      <div className="flex min-w-0 flex-[0_1_auto] overflow-hidden max-[819px]:order-last max-[819px]:basis-full">
        <ScenarioMenu />
      </div>
      <button
        type="button"
        onClick={toggleTheme}
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        className="inline-grid size-[34px] place-items-center rounded-md text-topbar-muted hover:bg-topbar-hover hover:text-on-topbar"
      >
        {theme === "dark" ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
      </button>
      <PersonaMenu />
    </header>
  );
}
