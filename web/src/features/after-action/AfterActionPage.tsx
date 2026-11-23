import { History, Info } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { useEffect, useRef, useState } from "react";
import { ContentsNav, EmptyState, LoadingState, PageHeader, ReportLayout } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { isPack } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import { PublishedEtr } from "../etr/PublishedEtr";
import { ReviewDraft } from "../etr/ReviewDraft";
import { BreakGlassTab } from "./BreakGlassTab";
import { ClocksTab } from "./ClocksTab";
import { ReportSection } from "./parts";
import { ReportTab } from "./ReportTab";
import { ScorecardTab } from "./ScorecardTab";
import { Summary } from "./Summary";
import { TimelineTab } from "./TimelineTab";
import { useAfterAction } from "./useAfterAction";
import { VerifyPanel } from "./VerifyPanel";
import { WhatHappenedSection } from "./WhatHappened";

/** `?tab=` keeps pointing at a section so links such as `/after-action?tab=timeline` still land in the right place. */
const TABS = ["clocks", "break-glass", "scorecard", "timeline", "report"] as const;
type Tab = (typeof TABS)[number];

const SECTIONS = [
  { id: "summary", label: "Status and numbers" },
  { id: "what-happened", label: "What happened" },
  { id: "audit-log", label: "Audit log" },
  { id: "deadlines", label: "Deadlines", tab: "clocks" },
  { id: "emergency", label: "Emergency approvals", tab: "break-glass" },
  { id: "accuracy", label: "ETR accuracy", tab: "scorecard" },
  { id: "timeline", label: "Timeline", tab: "timeline" },
  { id: "report", label: "PSC report", tab: "report" },
] as const satisfies readonly { id: string; label: string; tab?: Tab }[];

type SectionId = (typeof SECTIONS)[number]["id"];

/** Sections that need the Helene models or open data: left out of a scripted exercise's review. */
const HELENE_SECTIONS: ReadonlySet<SectionId> = new Set(["what-happened", "accuracy", "report"]);

function scrollToSection(id: SectionId, smooth: boolean) {
  const main = document.getElementById("main");
  const el = document.getElementById(id);
  if (!main || !el) return;
  const top =
    id === "summary"
      ? 0
      : el.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - 24;
  main.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
}

function ExerciseBanner() {
  return (
    <p
      role="note"
      data-testid="exercise-banner"
      className="m-0 flex items-start gap-2 border-y border-hair py-2.5 text-[13px] text-ink-2"
    >
      <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
      Exercise with synthetic data, not for operational use. Nothing here records a real event.
    </p>
  );
}

export default function AfterActionPage() {
  const review = useAfterAction();
  const scenario = useScenario();
  const [tab, setTab] = useQueryState("tab", parseAsStringLiteral(TABS).withOptions({ history: "replace" }));
  const [active, setActive] = useState<SectionId>("summary");
  const data = review.data;
  const scripted = isPack(scenario.data?.scenario);
  const sections = scripted ? SECTIONS.filter((s) => !HELENE_SECTIONS.has(s.id)) : SECTIONS;
  const scrolled = useRef(false);

  const go = (id: SectionId) => {
    scrollToSection(id, !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    setActive(id);
    const t = SECTIONS.find((s) => s.id === id);
    void setTab(t && "tab" in t ? t.tab : null);
  };

  useEffect(() => {
    if (!data || !tab || scrolled.current) return;
    scrolled.current = true;
    const target = SECTIONS.find((s) => "tab" in s && s.tab === tab);
    if (target) {
      scrollToSection(target.id, false);
      setActive(target.id);
    }
  }, [data, tab]);

  useEffect(() => {
    const main = document.getElementById("main");
    if (!main || !data) return;
    const onScroll = () => {
      const top = main.getBoundingClientRect().top + 96;
      let current: SectionId = "summary";
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= top) current = s.id;
      }
      setActive(current);
    };
    main.addEventListener("scroll", onScroll, { passive: true });
    return () => main.removeEventListener("scroll", onScroll);
  }, [data]);

  const missing =
    review.error instanceof ApiError && (review.error.status === 404 || review.error.status === 501);

  return (
    <ReportLayout
      contents={
        data && (
          <ContentsNav kind="button" items={sections} active={active} onGo={(id) => go(id as SectionId)} />
        )
      }
    >
      <div className="flex flex-col gap-8">
        <div className="flex flex-col gap-4">
          <PageHeader className="px-0 pb-0" title="After-action review" info="after_action" />
          {(scenario.data?.mode === "EXERCISE" || scripted) && <ExerciseBanner />}
          {review.isPending ? (
            <LoadingState rows={4} label="Loading review…" />
          ) : review.isError || !data ? (
            <EmptyState
              icon={History}
              role="alert"
              title={missing ? "The review isn't available yet." : "Couldn't load the review."}
              action={
                !missing && (
                  <Button variant="secondary" size="sm" onClick={() => void review.refetch()}>
                    Try again
                  </Button>
                )
              }
            />
          ) : (
            <Summary review={data} />
          )}
          {data && !scripted && <ReviewDraft />}
        </div>
        {data && (
          <>
            {!scripted && (
              <ReportSection id="what-happened" title="What happened">
                <WhatHappenedSection />
              </ReportSection>
            )}
            <ReportSection id="audit-log" title="Audit log">
              <VerifyPanel known={data.chain} />
            </ReportSection>
            <ReportSection id="deadlines" title="Deadlines" count={data.clocks.length}>
              <ClocksTab clocks={data.clocks} />
            </ReportSection>
            <ReportSection id="emergency" title="Emergency approvals" count={data.break_glass.length}>
              <BreakGlassTab uses={data.break_glass} />
            </ReportSection>
            {!scripted && (
              <ReportSection id="accuracy" title="ETR accuracy">
                <PublishedEtr card={data.scorecard} />
                <ScorecardTab card={data.scorecard} />
              </ReportSection>
            )}
            <ReportSection id="timeline" title="Timeline" count={data.timeline.length}>
              <TimelineTab entries={data.timeline} chain={data.chain} />
            </ReportSection>
            {!scripted && (
              <ReportSection id="report" title="PSC report">
                <ReportTab report={data.sc_report} chainOk={data.chain.ok} />
              </ReportSection>
            )}
          </>
        )}
      </div>
    </ReportLayout>
  );
}
