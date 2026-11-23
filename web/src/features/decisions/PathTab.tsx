import { Fragment } from "react";
import { InfoTip } from "@/components/sgw";
import type { components } from "@/contracts/api.gen";
import { cn } from "@/lib/cn";
import { formatDuration, formatEtZ } from "@/lib/time";
import { decisionTitle } from "./actionTypes";
import type { Chain } from "./chain";
import { PaneSection } from "./PaneSection";
import type { QueueItem } from "./useQueue";

type CaseChainStep = components["schemas"]["CaseChainStep"];

interface Props {
  chain: Chain;
  selectedId: string;
  now: string;
  onSelect: (proposalId: string) => void;
  /** The whole sequence of this decision from its case, shown first when present. */
  caseChain?: readonly CaseChainStep[];
}

/** The sequence of the case in decision order, each decision with its link or a plain "no proposal yet". */
function CaseSequence({
  steps,
  selectedId,
  onSelect,
}: {
  steps: readonly CaseChainStep[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <PaneSection title="Sequence" info="critical_path">
      <ol className="m-0 list-none p-0" aria-label="Steps in order">
        {[...steps]
          .sort((a, b) => a.order - b.order)
          .map((s) => {
            const current = s.proposal_id === selectedId;
            return (
              <li
                key={s.decision_case_id}
                data-testid="chain-step"
                aria-current={current ? "step" : undefined}
                className={cn("flex items-start gap-3 py-2", current && "bg-selected")}
              >
                <span
                  aria-hidden
                  data-now={current}
                  className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-full border-[1.5px] border-hair-strong text-[12px] font-semibold text-ink-2 [&[data-now=true]]:border-primary [&[data-now=true]]:bg-primary [&[data-now=true]]:text-on-primary"
                >
                  {s.order}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="sr-only">Step {s.order}: </span>
                  <span className="text-[14px] leading-[18px] font-medium">{decisionTitle(s.title)}</span>
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-muted tnum">
                    <span>decide by {formatEtZ(s.effective_decide_by_utc)}</span>
                    {current ? (
                      <span className="ml-auto font-medium text-ink-2">this decision</span>
                    ) : s.proposal_id ? (
                      <button
                        type="button"
                        onClick={() => onSelect(s.proposal_id as string)}
                        className="ml-auto text-[13px] font-semibold text-blue-ink hover:underline"
                      >
                        View decision ›
                      </button>
                    ) : (
                      <span className="ml-auto">No proposal yet</span>
                    )}
                  </span>
                </span>
              </li>
            );
          })}
      </ol>
      <p className="m-0 mt-3 text-[12px] text-muted">
        Each step must be decided before the next one can start.
      </p>
    </PaneSection>
  );
}

function OtherDecision({ item, onSelect }: { item: QueueItem; onSelect: (id: string) => void }) {
  const s = item.summary;
  return (
    <li className="flex flex-col gap-0.5 border-b border-hair py-2.5 last:border-b-0">
      <span className="text-[14px] leading-[18px] font-medium">{decisionTitle(s.title)}</span>
      <span className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => onSelect(s.proposal_id)}
          className="ml-auto text-[13px] font-semibold text-blue-ink hover:underline"
        >
          View decision ›
        </button>
      </span>
    </li>
  );
}

const LinkList = ({
  title,
  items,
  onSelect,
}: {
  title: string;
  items: QueueItem[];
  onSelect: (id: string) => void;
}) => (
  <div className="min-w-0">
    <h5 className="m-0 mb-1 text-[12px] font-semibold text-muted">{title}</h5>
    {items.length === 0 ? (
      <p className="m-0 text-[13px] text-muted">None</p>
    ) : (
      <ul className="m-0 list-none p-0">
        {items.map((i) => (
          <OtherDecision key={i.summary.proposal_id} item={i} onSelect={onSelect} />
        ))}
      </ul>
    )}
  </div>
);

/** The Sequence tab: numbered steps, each with its id and a link to open it. A link is red only when the buffer is negative. */
export function PathTab({ chain, selectedId, onSelect, caseChain }: Props) {
  if (caseChain && caseChain.length > 1) {
    return (
      <div className="flex flex-col" data-testid="path">
        <CaseSequence steps={caseChain} selectedId={selectedId} onSelect={onSelect} />
      </div>
    );
  }
  if (chain.steps.length === 0 && chain.blocks.length === 0 && chain.blockedBy.length === 0) {
    return (
      <PaneSection title="Sequence" info="critical_path">
        <p className="m-0 text-[13px] text-muted" data-testid="path-empty">
          Not linked to other decisions.
        </p>
      </PaneSection>
    );
  }
  return (
    <div className="flex flex-col" data-testid="path">
      {chain.steps.length > 0 && (
        <PaneSection title="Sequence" info="critical_path">
          <ol className="m-0 list-none p-0" aria-label="Steps in order">
            {chain.steps.map((s) => {
              const current = s.item.summary.proposal_id === selectedId;
              return (
                <Fragment key={s.caseId}>
                  {s.incoming.map((link) =>
                    link.slackMin === null ? null : (
                      <li
                        key={`${link.from}-${s.n}`}
                        aria-label={link.slackMin < 0 ? "No buffer" : "Has buffer"}
                        data-testid="chain-link"
                        data-negative={link.slackMin < 0}
                        className={cn(
                          "ml-[13px] flex items-center gap-2 border-l-2 py-1 pl-5 text-[12px] tnum",
                          link.slackMin < 0
                            ? "border-crit font-medium text-crit"
                            : "border-hair-strong text-muted",
                        )}
                      >
                        {link.from} → {s.n}:{" "}
                        {link.slackMin < 0
                          ? `short by ${formatDuration(link.slackMin)}`
                          : `${formatDuration(link.slackMin)} to spare`}
                        <InfoTip term="slack" />
                      </li>
                    ),
                  )}
                  <li
                    data-testid="chain-step"
                    aria-current={current ? "step" : undefined}
                    className={cn("flex items-start gap-3 py-2", current && "bg-selected")}
                  >
                    <span
                      aria-hidden
                      className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-full border-[1.5px] border-hair-strong text-[12px] font-semibold text-ink-2 [&[data-now=true]]:border-primary [&[data-now=true]]:bg-primary [&[data-now=true]]:text-on-primary"
                      data-now={current}
                    >
                      {s.n}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="sr-only">Step {s.n}: </span>
                      <span data-testid="chain-step-title" className="text-[14px] leading-[18px] font-medium">
                        {decisionTitle(s.item.summary.title)}
                      </span>
                      <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-muted tnum">
                        <span>decide by {formatEtZ(s.item.summary.effective_decide_by_utc)}</span>
                        {current ? (
                          <span className="ml-auto font-medium text-ink-2">this decision</span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => onSelect(s.item.summary.proposal_id)}
                            className="ml-auto text-[13px] font-semibold text-blue-ink hover:underline"
                          >
                            View decision ›
                          </button>
                        )}
                      </span>
                    </span>
                  </li>
                </Fragment>
              );
            })}
          </ol>
          <p className="m-0 mt-3 text-[12px] text-muted">
            1 → 2: step 1 must be decided before step 2 can start.
          </p>
        </PaneSection>
      )}
      <PaneSection title="Depends on and needed by">
        <div className="flex flex-col gap-4">
          <LinkList title="Depends on" items={chain.blockedBy} onSelect={onSelect} />
          <LinkList title="Needed by" items={chain.blocks} onSelect={onSelect} />
        </div>
      </PaneSection>
    </div>
  );
}
