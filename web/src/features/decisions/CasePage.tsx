import { useNavigate, useParams } from "react-router";
import { ErrorState, PageHeader } from "@/components/sgw";
import { Skeleton } from "@/components/ui/skeleton";
import { AssignedCrews } from "@/features/crews/AssignedCrews";
import { decisionHref, decisionPageHref } from "@/lib/links";
import { useScenarioNow } from "@/sse/useScenarioNow";
import { ApprovalTab } from "./ApprovalTab";
import { decisionTitle } from "./actionTypes";
import { BasisTab } from "./BasisTab";
import { CaseHeader } from "./CaseHeader";
import { useCriticalChain } from "./chain";
import { HistoryTab } from "./HistoryTab";
import { PathTab } from "./PathTab";
import { caseChainOf } from "./ui";
import { useCard, useListed } from "./useQueue";

/** The second disclosure level: the whole decision on one page, no tabs. */
export default function CasePage() {
  const { proposalId = "" } = useParams();
  const navigate = useNavigate();
  const now = useScenarioNow() ?? new Date().toISOString();
  const listed = useListed(proposalId);
  const { data: card, isPending, error } = useCard(listed.id);
  const chain = useCriticalChain(proposalId, now);
  const crumbs = [
    { label: "SGW", to: "/" },
    { label: "Respond" },
    { label: "Decisions", to: decisionHref(proposalId) },
    { label: card ? decisionTitle(card.title) : "Decision" },
  ];
  return (
    <div className="mx-auto flex min-h-full max-w-[1240px] flex-col">
      <PageHeader breadcrumb={crumbs} title="Decision" info="queue" />
      {listed.gone ? (
        <ErrorState thing="This decision" title="This decision isn't in the loaded scenario." />
      ) : isPending ? (
        <Skeleton className="mx-8 h-40" />
      ) : error || !card ? (
        <ErrorState thing="This decision" title="Couldn't load this decision." error={error ?? undefined} />
      ) : (
        <div className="flex flex-col gap-8 px-8 pb-10" data-testid="case-page">
          <div className="max-w-[720px]">
            <CaseHeader card={card} now={now} />
            <div className="mt-3 empty:hidden">
              <AssignedCrews caseId={card.decision_case_id} />
            </div>
          </div>
          <div className="grid gap-x-10 border-t border-hair pt-6 min-[1100px]:grid-cols-2">
            <div className="flex min-w-0 flex-col">
              <BasisTab card={card} now={now} />
            </div>
            <div className="flex min-w-0 flex-col">
              <ApprovalTab card={card} />
              <PathTab
                chain={chain}
                selectedId={card.proposal_id}
                now={now}
                onSelect={(id) => navigate(decisionPageHref(id))}
                caseChain={caseChainOf(card)}
              />
              <HistoryTab card={card} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
