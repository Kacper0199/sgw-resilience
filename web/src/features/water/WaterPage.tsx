import { parseAsStringLiteral, useQueryState } from "nuqs";
import { Link } from "react-router";
import { CountTabs, type KeyNumber, KeyNumberStrip, PageHeader } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { loadFailureLine } from "@/lib/loadFailure";
import { formatET } from "@/lib/time";
import { useScenarioNow } from "@/sse/useScenarioNow";
import { AdvisoryContainer } from "./AdvisoryContainer";
import { ClocksContainer } from "./ClocksContainer";
import { zoneName } from "./format";
import { waitingForSignOff } from "./lifecycle";
import type { WaterTab } from "./types";
import { orderCases, useAdvisories, useWaterCases, useZoneNotices, useZones } from "./useWater";
import { ZonesContainer } from "./ZonesContainer";

const TABS = ["zones", "plan", "advisories"] as const satisfies readonly WaterTab[];
const DASH = "—";

function useKeyNumbers(): { items: KeyNumber[]; chain: number; advisories: number; waiting: number } {
  const zones = useZones();
  const cases = useWaterCases();
  const adv = useAdvisories();

  const list = zones.data ?? [];
  const above = list.filter((z) => z.pressure_psi_x10 >= z.floor_psi_x10).length;
  const floor = list[0] ? list[0].floor_psi_x10 / 10 : undefined;
  const next = [...cases.cards].sort(
    (a, b) => Date.parse(a.effective_decide_by_utc) - Date.parse(b.effective_decide_by_utc),
  )[0];
  const inPlay = useZoneNotices().notices;
  const waiting = waitingForSignOff(inPlay);
  const firstWaiting = waiting[0];

  const items: KeyNumber[] = [
    {
      label: "Zones above the minimum",
      value: zones.data ? (
        <>
          {above} <span className="text-[13px] font-normal text-muted">of {list.length}</span>
        </>
      ) : (
        DASH
      ),
      line: zones.error
        ? loadFailureLine(zones.error)
        : floor !== undefined
          ? `Minimum is ${floor.toFixed(0)} psi`
          : undefined,
      tone: zones.data && above < list.length ? "crit" : undefined,
      info: "pressure_floor",
    },
    {
      label: "Open deadlines",
      value: cases.error || cases.isPending ? DASH : cases.cards.length,
      line: cases.error
        ? loadFailureLine(cases.error)
        : next
          ? `Next ${formatET(next.effective_decide_by_utc)}`
          : cases.isPending
            ? undefined
            : "No open water decisions",
    },
    {
      label: "Notice waiting for sign-off",
      value: adv.data ? waiting.length : DASH,
      line: adv.error
        ? loadFailureLine(adv.error)
        : !adv.data
          ? undefined
          : firstWaiting
            ? `${zoneName(firstWaiting.zoneId)}${firstWaiting.dueUtc ? `, due ${formatET(firstWaiting.dueUtc)}` : ""}`
            : "Nothing waiting",
      tone: waiting.length > 0 ? "warn" : undefined,
      info: "bwa",
    },
  ];
  return {
    items,
    chain: orderCases(cases.cards).chain.length || cases.cards.length,
    advisories: inPlay.length,
    waiting: waiting.length,
  };
}

export default function WaterPage() {
  const now = useScenarioNow() ?? new Date().toISOString();
  const [tab, setTab] = useQueryState("tab", parseAsStringLiteral(TABS).withDefault("zones"));
  const zones = useZones();
  const { items, chain, advisories, waiting } = useKeyNumbers();
  return (
    <div className="min-h-full">
      <PageHeader
        title="Water"
        info="page_water"
        actions={
          <Button variant="secondary" asChild>
            <Link to="/map">Map</Link>
          </Button>
        }
      />
      <KeyNumberStrip items={items} />
      <CountTabs
        label="Water views"
        value={tab}
        onValueChange={(v) => void setTab(v as WaterTab)}
        listClassName="px-8"
        contentClassName="pt-0"
        tabs={[
          {
            value: "zones",
            label: "Zones",
            count: zones.data?.length,
            content: <ZonesContainer now={now} onOpenTab={(t) => void setTab(t)} />,
          },
          {
            value: "plan",
            label: "PS-17 plan",
            count: chain || undefined,
            content: <ClocksContainer now={now} />,
          },
          {
            value: "advisories",
            label: "Boil-water notices",
            count: advisories || undefined,
            tone: waiting > 0 ? "warn" : undefined,
            content: <AdvisoryContainer now={now} />,
          },
        ]}
      />
    </div>
  );
}
