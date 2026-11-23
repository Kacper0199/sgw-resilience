import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { useState } from "react";
import { CountTabs, type KeyNumber, KeyNumberStrip, PageHeader } from "@/components/sgw";
import { isPack } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import { useRegions } from "../map/data";
import { CrewsTable } from "./CrewsTable";
import { DamageQueue } from "./DamageQueue";
import { int, reportingArea } from "./format";
import { GeneratorsContainer } from "./GeneratorsContainer";
import { useBeforeLandfall } from "./landfall";
import { PlanOptions } from "./PlanOptions";
import { useCrewList, useDamageQueue } from "./useCrews";
import { YardsContainer } from "./YardsContainer";

const TABS = ["crews", "plan", "photos"] as const;
const DASH = "—";

const SCRIPTED: KeyNumber = { label: "Source", value: "Scripted", line: "Exercise data (synthetic)" };

function useKeyNumbers(scripted: boolean): { items: KeyNumber[]; crews?: number; cases?: number } {
  const crewsQ = useCrewList();
  const damageQ = useDamageQueue();
  const regions = useRegions();
  const crews = crewsQ.data;
  const people = crews?.reduce((n, c) => n + c.headcount, 0) ?? 0;
  const area = crews ? reportingArea(crews, regions.data) : null;
  const count = (status: string) => crews?.filter((c) => c.status === status).length ?? 0;
  const working = count("enroute") + count("onsite");
  const blocked = count("blocked");
  const free = crews?.filter((c) => c.status === "available" && !c.assignment).length ?? 0;
  const toSign = crews?.filter((c) => c.assignment?.state === "proposed").length ?? 0;
  const early = useBeforeLandfall();
  const cases = early ? 0 : damageQ.data?.cases.length;
  return {
    crews: crews?.length,
    cases,
    items: [
      {
        label: "Crews reporting",
        value: crews ? crews.length : DASH,
        line: crews ? `${int(people)} people${area ? ` in ${area}` : ""}` : undefined,
      },
      {
        label: "Available now",
        value: crews ? free : DASH,
        line: crews
          ? toSign > 0
            ? `${toSign} waiting for sign-off`
            : `${count("staged")} staged, ${working} working`
          : undefined,
      },
      {
        label: "Crews blocked",
        value: crews ? blocked : DASH,
        line: blocked > 0 ? "Check road access first" : undefined,
        tone: blocked > 0 ? "warn" : undefined,
      },
      scripted
        ? SCRIPTED
        : {
            label: "Damage cases to review",
            value: cases ?? DASH,
            line: early
              ? "Photos come in after landfall"
              : damageQ.data
                ? `${damageQ.data.total_photos} photos`
                : undefined,
          },
    ],
  };
}

export default function CrewsPage() {
  const [crew] = useQueryState("crew", parseAsString);
  const [yard] = useQueryState("yard", parseAsString);
  const [photo] = useQueryState("photo", parseAsString);
  const [opened] = useState<(typeof TABS)[number]>(photo ? "photos" : yard && !crew ? "plan" : "crews");
  const [tab, setTab] = useQueryState("tab", parseAsStringLiteral(TABS).withDefault(opened));
  const scripted = isPack(useScenario().data?.scenario);
  const { items, crews, cases } = useKeyNumbers(scripted);
  const crewsTab = {
    value: "crews",
    label: "Crews",
    count: crews,
    content: <CrewsTable focus={crew} />,
  } as const;
  return (
    <div className="min-h-full">
      <PageHeader title="Crews" info="page_crews" />
      <KeyNumberStrip items={items} />
      <CountTabs
        label="Crews views"
        value={tab}
        onValueChange={(v) => void setTab(v as (typeof TABS)[number])}
        listClassName="px-8"
        contentClassName="pt-0"
        tabs={
          scripted
            ? [crewsTab]
            : [
                crewsTab,
                {
                  value: "plan",
                  label: "Plan",
                  content: (
                    <>
                      <PlanOptions />
                      <div className="grid items-start gap-x-10 gap-y-8 px-8 py-5 min-[1280px]:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                        <YardsContainer focus={yard} />
                        <GeneratorsContainer />
                      </div>
                    </>
                  ),
                },
                { value: "photos", label: "Damage photos", count: cases, content: <DamageQueue /> },
              ]
        }
      />
    </div>
  );
}
