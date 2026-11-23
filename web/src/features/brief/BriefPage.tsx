import { FileText } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { EmptyState, PageHeader, SegmentedControl } from "@/components/sgw";
import { Skeleton } from "@/components/ui/skeleton";
import { ReasonTip } from "@/features/decisions/ReasonTip";
import { ApiError } from "@/lib/api";
import { isPack } from "@/lib/scenarios";
import { useScenario, useScenarioNow } from "@/sse/useScenarioNow";
import { FourNumbers } from "./FourNumbers";
import { FunctionLines } from "./FunctionLines";
import { OnThisPage } from "./OnThisPage";
import { OpenClocks } from "./OpenClocks";
import { PrintBrief } from "./PrintBrief";
import { SitrepContainer } from "./SitrepContainer";
import { StatusHeader } from "./StatusHeader";
import { SurgeLine } from "./SurgeLine";
import { useBrief } from "./useBrief";
import { WhatChanged } from "./WhatChanged";

const TOC = [
  { id: "status", label: "Status and numbers" },
  { id: "deadlines", label: "Decisions needing two teams" },
  { id: "changed", label: "What changed" },
  { id: "team", label: "By team" },
  { id: "sitrep", label: "Situation report" },
] as const;
const SHOW = [
  { value: "actual", label: "Now" },
  { value: "forecast", label: "Forecast" },
] as const;

export default function BriefPage() {
  return <BriefView now={useScenarioNow()} />;
}

const frame = "w-full px-8 max-[819px]:px-4";

export function BriefView({ now }: { now: string | null }) {
  const brief = useBrief();
  const scripted = isPack(useScenario().data?.scenario);
  const [chosen, setBasis] = useQueryState(
    "show",
    parseAsStringLiteral(["actual", "forecast"] as const).withDefault("actual"),
  );

  if (brief.isPending) {
    return (
      <div className={`${frame} flex flex-col gap-4 py-6`} role="status" aria-label="Loading briefing…">
        <Skeleton className="h-24" />
        <Skeleton className="h-32" />
      </div>
    );
  }
  if (brief.error || !brief.data) {
    return (
      <div className={frame}>
        <PageHeader className="px-0" title="Briefing" />
        <EmptyState
          role="alert"
          icon={FileText}
          title={
            brief.error instanceof ApiError && brief.error.status === 404
              ? "The briefing isn't available yet."
              : "Couldn't load the briefing. Try again in a moment."
          }
        />
      </div>
    );
  }
  const b = brief.data;
  const basis = scripted ? "actual" : chosen;
  return (
    <div
      data-print-page="brief"
      className={`${frame} grid grid-cols-[minmax(0,1fr)] gap-x-12 pb-16 min-[1100px]:grid-cols-[minmax(0,820px)_200px]`}
    >
      <div className="min-w-0">
        <PageHeader
          className="px-0"
          title="Briefing"
          info="page_brief"
          actions={
            <>
              <ReasonTip label="About these numbers" title="About these numbers">
                <p className="m-0" data-testid="caveat">
                  {b.caveat}
                </p>
                <p className="m-0" data-testid="brief-footer">
                  {b.footer}
                </p>
              </ReasonTip>
              {!scripted && (
                <SegmentedControl
                  label="Show"
                  value={basis}
                  onValueChange={(v) => void setBasis(v)}
                  options={SHOW}
                />
              )}
              <PrintBrief />
            </>
          }
        />
        <section id="status" aria-label="Status and numbers" className="scroll-mt-4">
          <StatusHeader brief={b} />
          <FourNumbers numbers={b.numbers} basis={basis} />
          {!scripted && <SurgeLine asOf={b.as_of} />}
        </section>
        <div id="deadlines" className="mt-10 scroll-mt-4">
          <OpenClocks clocks={b.open_t3} now={now ?? b.as_of} />
        </div>
        <div id="changed" className="mt-10 scroll-mt-4">
          <WhatChanged advisory={b.last_advisory} now={now ?? b.as_of} />
        </div>
        <div id="team" className="mt-10 scroll-mt-4">
          <FunctionLines lines={b.functions} />
        </div>
        {!scripted && (
          <div id="sitrep" className="mt-10 scroll-mt-4">
            <SitrepContainer sitrep={b.sitrep} />
          </div>
        )}
      </div>
      <OnThisPage items={scripted ? TOC.filter((i) => i.id !== "sitrep") : TOC} />
    </div>
  );
}
