import { TooltipProvider } from "@/components/ui/tooltip";
import { useTheme } from "../layout/useTheme";
import { useReducedTransparency } from "../layout/useTransparency";
import { Specimen } from "./Specimen";

/** Dev-only: every primitive in light and dark, for developers and reviewers. Not in the navigation. */
export default function DesignCheckPage() {
  const [reduced, setReduced] = useReducedTransparency();
  const [theme, toggleTheme] = useTheme();
  return (
    <TooltipProvider>
      <main id="main" className="min-h-full bg-canvas">
        <div className="flex items-center gap-4 border-b border-hair bg-surface px-8 py-3 text-ink">
          <h1 className="m-0 text-[16px] font-bold">Design check</h1>
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={reduced} onChange={(e) => setReduced(e.target.checked)} />
            Reduce transparency
          </label>
          <button
            type="button"
            onClick={toggleTheme}
            className="text-[13px] font-medium text-blue-ink hover:underline"
          >
            Page theme: {theme} (dialogs and sheets follow it)
          </button>
        </div>
        <div className="grid min-[1800px]:grid-cols-2">
          <div data-theme="light" data-testid="specimen-light">
            <Specimen />
          </div>
          <div data-theme="dark" data-testid="specimen-dark">
            <Specimen />
          </div>
        </div>
      </main>
    </TooltipProvider>
  );
}
