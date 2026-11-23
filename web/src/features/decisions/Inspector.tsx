import { ClipboardList, X } from "lucide-react";
import { forwardRef, lazy, Suspense, useRef } from "react";
import { Link } from "react-router";
import { CountTabs, EmptyState, ErrorState } from "@/components/sgw";
import { IconButton } from "@/components/ui/icon-button";
import { Skeleton } from "@/components/ui/skeleton";
import { AssignedCrews } from "@/features/crews/AssignedCrews";
import { decisionPageHref } from "@/lib/links";
import { ApprovalTab } from "./ApprovalTab";
import { BasisTab } from "./BasisTab";
import { CaseHeader } from "./CaseHeader";
import { useCriticalChain } from "./chain";
import { HistoryTab } from "./HistoryTab";
import { PathTab } from "./PathTab";
import { caseChainOf } from "./ui";
import { useCard } from "./useQueue";
import type { InspectorTab } from "./useQueueUrlState";

const MapContainer = lazy(() => import("@/features/map/MapContainer"));

interface Props {
  id: string | null;
  now: string;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onClose: () => void;
  onSelectCase?: (proposalId: string) => void;
  onSelectProposal?: (proposalId: string) => void;
}

/** The decision pane: the map strip, then the case header and the five tabs. No cards inside it. */
export const Inspector = forwardRef<HTMLHeadingElement, Props>(function Inspector(
  { id, now, tab, onTab, onClose, onSelectCase, onSelectProposal },
  ref,
) {
  const { data: card, isPending, error } = useCard(id);
  const chain = useCriticalChain(id, now);
  const tabsBody = useRef<HTMLDivElement>(null);
  const strip = (
    <div className={id ? "h-[clamp(190px,28vh,300px)] shrink-0" : "h-[48%] min-h-[220px] shrink-0"}>
      <Suspense fallback={<Skeleton className="h-full rounded-none" />}>
        <MapContainer selectedProposalId={id} onSelectProposal={onSelectProposal} variant="strip" />
      </Suspense>
    </div>
  );
  if (!id) {
    return (
      <div className="flex h-full flex-col">
        {strip}
        <EmptyState icon={ClipboardList} title="Select a decision to see its details." />
      </div>
    );
  }
  if (isPending) {
    return (
      <div className="flex flex-col">
        {strip}
        <Skeleton className="m-6 h-40" />
      </div>
    );
  }
  if (error || !card) {
    return (
      <div className="flex flex-col">
        {strip}
        <ErrorState thing="This decision" title="Couldn't load this decision." error={error ?? undefined} />
      </div>
    );
  }
  const select = onSelectCase ?? (() => {});
  const switchTab = (next: InspectorTab) => {
    const scroller = tabsBody.current?.closest<HTMLElement>("[data-scroll-region]");
    if (scroller && tabsBody.current) {
      const tabsTop =
        tabsBody.current.getBoundingClientRect().top -
        scroller.getBoundingClientRect().top +
        scroller.scrollTop;
      if (scroller.scrollTop > tabsTop) scroller.scrollTop = tabsTop;
    }
    onTab(next);
  };
  return (
    <div className="flex flex-col">
      {strip}
      <div className="px-6 pt-4" data-testid="inspector">
        <CaseHeader
          key={card.proposal_id}
          ref={ref}
          card={card}
          now={now}
          trailing={
            <>
              <Link
                to={decisionPageHref(card.proposal_id)}
                aria-label="Open full page"
                className="text-[13px] font-semibold text-blue-ink hover:underline"
              >
                Open full page
              </Link>
              <IconButton small label="Close details" icon={<X />} onClick={onClose} />
            </>
          }
        />
        <div className="mt-3 empty:hidden">
          <AssignedCrews caseId={card.decision_case_id} />
        </div>
      </div>
      <div ref={tabsBody} className="mt-4 flex-1 px-6">
        <CountTabs
          label="Decision details"
          listClassName="sticky top-0 z-10 gap-4"
          contentClassName="min-h-[calc(100dvh-97px)]"
          value={tab}
          onValueChange={(v) => switchTab(v as InspectorTab)}
          tabs={[
            { value: "deadline", label: "Deadline", content: <BasisTab card={card} now={now} /> },
            {
              value: "signatures",
              label: "Signatures",
              count: card.functions_required.length,
              content: <ApprovalTab card={card} />,
            },
            {
              value: "sequence",
              label: "Sequence",
              count: Math.max(chain.steps.length, caseChainOf(card)?.length ?? 0) || undefined,
              content: (
                <PathTab
                  chain={chain}
                  selectedId={card.proposal_id}
                  now={now}
                  onSelect={select}
                  caseChain={caseChainOf(card)}
                />
              ),
            },
            {
              value: "history",
              label: "History",
              content: <HistoryTab card={card} />,
            },
          ]}
        />
      </div>
    </div>
  );
});
