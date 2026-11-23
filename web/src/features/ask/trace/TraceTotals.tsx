import { compact, cost, ms } from "./format";
import { MODE_LABEL } from "./labels";
import type { Totals } from "./model";

function Cell({ value, caption }: { value: string; caption: string }) {
  return (
    <div className="min-w-0">
      <p className="m-0 text-[18px] leading-6 font-semibold tnum">{value}</p>
      <p className="m-0 mt-0.5 truncate text-[12px] leading-4 text-muted">{caption}</p>
    </div>
  );
}

/** The four numbers of the run: time, AI calls, tokens, cost. */
export function TraceTotals({ totals }: { totals: Totals }) {
  const mode = totals.modes.map((m) => MODE_LABEL[m]).join(" + ");
  return (
    <section
      aria-label="Totals"
      data-testid="trace-totals"
      className="grid shrink-0 grid-cols-[1fr_1fr_1.35fr_1fr] gap-x-4 border-b border-hair px-6 py-4"
    >
      <Cell value={ms(totals.ms)} caption="Time" />
      <Cell value={String(totals.llmCalls)} caption={mode ? `AI calls, ${mode.toLowerCase()}` : "AI calls"} />
      <Cell
        value={`${compact(totals.tokensIn)} / ${compact(totals.tokensOut)}`}
        caption={totals.cacheRead > 0 ? `In / out, ${compact(totals.cacheRead)} cached` : "Tokens in / out"}
      />
      <Cell value={totals.billed ? cost(totals.costMicros) : "No cost"} caption="Cost" />
    </section>
  );
}
