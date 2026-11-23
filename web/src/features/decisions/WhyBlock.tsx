import { plainAdvisory } from "@/lib/advisory";
import type { ProposalCard } from "@/lib/api";
import { usePhase } from "@/lib/PhaseProvider";
import { etText, plainFunctions } from "@/lib/plain";
import { ReasonTip } from "./ReasonTip";
import { buildWhy } from "./whyModel";

/** The (i) next to Timing: up to three plain reasons and what would change the verdict. */
export function WhyTip({ card }: { card: ProposalCard }) {
  const why = buildWhy(card, usePhase().advisoriesOver);
  if (!why.verdictLabel) return null;
  const reasons = why.reasons.map((r) =>
    plainAdvisory(
      plainFunctions(etText(r.replace(/\s*\(DC-[A-Z0-9-]+\)/g, ""), card.effective_decide_by_utc)),
    ),
  );
  return (
    <ReasonTip label="Why this timing" title="Why this timing">
      <ul className="m-0 list-disc pl-4" data-testid="why-block">
        {reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {why.limit && <p className="m-0">{why.limit}</p>}
    </ReasonTip>
  );
}
