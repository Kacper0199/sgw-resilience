import { Section } from "@/components/sgw";
import type { ProposalState } from "@/contracts/vocab.gen";
import type { ProposalSummary } from "@/lib/api";
import { formatDuration, formatETOn } from "@/lib/time";
import { ViewDecision } from "../agent-panel/decisionLink";
import { decisionTitle } from "../decisions/actionTypes";
import { useProposals } from "../decisions/useQueue";
import type { Brief } from "./types";

const RANK: Record<ProposalState, number> = {
  proposed: 0,
  in_review: 0,
  escalated: 0,
  draft: 0,
  approved: 1,
  executed: 1,
  rejected: 2,
  withdrawn: 2,
  expired: 2,
};

/** One row per decision case: the live proposal first, then the decided one, then the closed ones. */
export function movedByAdvisory(proposals: readonly ProposalSummary[], label: string): ProposalSummary[] {
  const best = new Map<string, ProposalSummary>();
  for (const p of proposals) {
    if (p.clock_shift?.advisory_label !== label) continue;
    const held = best.get(p.decision_case_id);
    const better =
      !held ||
      RANK[p.state] < RANK[held.state] ||
      (RANK[p.state] === RANK[held.state] && p.proposal_version > held.proposal_version);
    if (better) best.set(p.decision_case_id, p);
  }
  return [...best.values()];
}

/** Deadlines the latest advisory moved, read from the server's own clock shifts. After the final advisory
 * no advisory moves anything any more, and the section says so. */
export function WhatChanged({ advisory, now }: { advisory: Brief["last_advisory"]; now: string }) {
  const proposals = useProposals().data ?? [];
  const moved = advisory ? movedByAdvisory(proposals, advisory.label) : [];
  const final = advisory !== null && advisory.next_utc === null;
  const title = advisory && !final ? "What changed at the latest advisory" : "What changed";
  return (
    <Section title={title}>
      {final && (
        <p className="m-0 mb-2.5 text-[14px] text-muted" data-testid="final-advisory">
          The final advisory was issued {formatETOn(advisory.issued_utc, now)}. No advisories follow.
        </p>
      )}
      {moved.length === 0 ? (
        !final && (
          <p className="m-0 text-[14px] text-muted" data-testid="nothing-changed">
            {advisory ? "No decision deadline has moved at the latest advisory." : "No advisory issued yet."}
          </p>
        )
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2.5 p-0" data-testid="changed-list">
          {moved.map((p) => {
            const s = p.clock_shift;
            if (!s) return null;
            const earlier = s.shift_min < 0;
            return (
              <li key={p.proposal_id} className="text-[15px] leading-6">
                <b className="font-semibold">{decisionTitle(p.title)}.</b> Due{" "}
                {formatETOn(s.previous_effective_decide_by_utc, now)} at the previous advisory, now{" "}
                {formatETOn(p.effective_decide_by_utc, now)}, {earlier ? "earlier" : "later"} by{" "}
                {formatDuration(s.shift_min)}. <ViewDecision id={p.proposal_id} />
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}
