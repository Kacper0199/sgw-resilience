import { ChevronRight, Droplets } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import {
  ClockText,
  type DataColumn,
  DataTable,
  EmptyState,
  LoadingState,
  Sparkline,
  StatusText,
} from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { decisionTitle } from "@/features/decisions/actionTypes";
import type { ProposalCard } from "@/lib/api";
import { cn } from "@/lib/cn";
import { loadFailureTitle } from "@/lib/loadFailure";
import { assetName } from "@/lib/names";
import { FOCUS_ROW_CLASS, useFocusRow } from "@/lib/useFocusRow";
import { AdvisoryForecast, NoticeStatus } from "./AdvisoryContainer";
import { earliestId, StepRow } from "./ClocksContainer";
import { DecisionLinks } from "./DecisionLinks";
import { backupPower, generatorOrdered, psi, zoneName } from "./format";
import { LoadFailed } from "./LoadFailed";
import { noticeLifecycle, type ZoneNotice } from "./lifecycle";
import { NoticeStepper } from "./NoticeStepper";
import { PressureBar } from "./PressureBar";
import type { BwaAdvisory, WaterTab, WaterZoneWithHistory } from "./types";
import { orderCases, useAdvisories, usePolicies, useWaterCases, useZones } from "./useWater";

const NOTICE_ACTIONS = new Set<ProposalCard["action_type"]>(["boil_water_notice", "lift_boil_water_notice"]);

const PARAM_TARGETS = ["zone_id", "station_id", "serves_id", "destination_id", "replaces_id"] as const;

/** What a decision acts on: its targets plus the zone, station, facility or destination its parameters name (a tanker targets the truck, not the hospital it serves). */
export function cardTargets(card: ProposalCard): string[] {
  const named = PARAM_TARGETS.flatMap((key) => {
    const v = card.params?.[key];
    return typeof v === "string" ? [v] : [];
  });
  return [...card.target_ids, ...named];
}

function targetsOf(zone: WaterZoneWithHistory): Set<string> {
  return new Set([zone.zone_id, zone.pump_station_id, ...zone.critical_facility_ids]);
}

/** The earliest open water decision that targets this zone's station or one of its critical facilities. */
export function nextDecision(zone: WaterZoneWithHistory, cards: ProposalCard[]): ProposalCard | undefined {
  const targets = targetsOf(zone);
  return cards
    .filter((c) => cardTargets(c).some((t) => targets.has(t)))
    .sort((a, b) => Date.parse(a.effective_decide_by_utc) - Date.parse(b.effective_decide_by_utc))[0];
}

/** The steps for this zone: its critical path in order, then its other open decisions. */
export function zoneSteps(
  zone: WaterZoneWithHistory,
  cards: ProposalCard[],
): { steps: ProposalCard[]; ordered: boolean; numbered: number } {
  const targets = targetsOf(zone);
  const { chain, others } = orderCases(
    cards.filter((c) => !NOTICE_ACTIONS.has(c.action_type) && cardTargets(c).some((t) => targets.has(t))),
  );
  return { steps: [...chain, ...others], ordered: chain.length > 0, numbered: chain.length };
}

const isAbnormal = (z: WaterZoneWithHistory, cards: ProposalCard[], notice: ZoneNotice | undefined) =>
  z.pressure_psi_x10 < z.floor_psi_x10 ||
  nextDecision(z, cards) !== undefined ||
  (notice !== undefined && notice.status.level !== "normal" && notice.status.level !== "advisory");

function NoticeBlock({
  notice,
  advisories,
  threshold,
  now,
  onOpenTab,
}: {
  notice: ZoneNotice;
  advisories: BwaAdvisory[];
  threshold: number | undefined;
  now: string;
  onOpenTab?: (tab: WaterTab) => void;
}) {
  const name = zoneName(notice.zoneId);
  const forecast = notice.current === "due" ? advisories.find((a) => a.assessments.length > 0) : undefined;
  return (
    <div className="mb-4 last:mb-0">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-x-4">
        <h3 className="m-0 text-[16px] font-bold">Boil-water notice</h3>
        <div className="flex flex-wrap items-center gap-x-4">
          <Button variant="tertiary" size="sm" className="px-0" onClick={() => onOpenTab?.("advisories")}>
            Rules cited and detail
            <ChevronRight aria-hidden />
          </Button>
          {notice.decision && (
            <DecisionLinks proposalId={notice.decision.proposal_id} title={`Boil-water notice, ${name}`} />
          )}
        </div>
      </div>
      <NoticeStatus status={notice.status} dueUtc={notice.dueUtc} now={now} />
      <div className="mt-2 mb-1 max-w-[460px]">
        <NoticeStepper notice={notice} zoneLabel={name} />
      </div>
      {forecast && (
        <div className="mt-2">
          <AdvisoryForecast advisory={forecast} threshold={threshold} width={460} stats={false} />
        </div>
      )}
    </div>
  );
}

function ZoneDetail({
  zone,
  cards,
  notice,
  advisories,
  advisoriesError,
  threshold,
  now,
  onOpenTab,
}: {
  zone: WaterZoneWithHistory;
  cards: ProposalCard[];
  notice: ZoneNotice | undefined;
  advisories: BwaAdvisory[];
  advisoriesError: unknown;
  threshold: number | undefined;
  now: string;
  onOpenTab?: (tab: WaterTab) => void;
}) {
  const { steps, ordered, numbered } = zoneSteps(zone, cards);
  const name = zoneName(zone.zone_id);
  if (steps.length === 0 && !notice && !advisoriesError) {
    return (
      <p className="m-0 text-[13px] text-muted">
        Pressure is above the minimum. No open decision for {name}.
      </p>
    );
  }
  const firstId = earliestId(steps);
  return (
    <div
      className="-mx-8 grid max-[819px]:sticky max-[819px]:left-4 max-[819px]:mx-0 max-[819px]:w-[calc(100vw-48px)] min-[1100px]:grid-cols-2"
      data-testid="zone-detail"
    >
      <div className="min-w-0 px-8 min-[1100px]:border-r min-[1100px]:border-hair">
        <h3 className="m-0 mb-1 text-[16px] font-bold">Next steps for {name}</h3>
        <p className="m-0 text-[13px] text-muted">
          {zone.critical_facility_ids.length > 0 && (
            <>Serves {zone.critical_facility_ids.map(assetName).join(", ")}. </>
          )}
          {steps.length === 0
            ? "No other open decisions"
            : `${steps.length} ${steps.length === 1 ? "step" : "steps"}`}
          {ordered && numbered === steps.length && steps.length > 1 ? " in order" : ""}
        </p>
        <ol className="m-0 mt-1 list-none p-0">
          {steps.map((c, i) => (
            <StepRow
              key={c.proposal_id}
              card={c}
              now={now}
              number={i < numbered ? i + 1 : undefined}
              first={c.proposal_id === firstId}
              showBasis={false}
              compact
            />
          ))}
        </ol>
      </div>
      <div className="min-w-0 px-8">
        {advisoriesError || !notice ? (
          <>
            <h3 className="m-0 mb-1 text-[16px] font-bold">Boil-water notice</h3>
            {advisoriesError ? (
              <p className="m-0 text-[13px] text-muted" role="alert">
                {loadFailureTitle(advisoriesError, "boil-water notices")}
              </p>
            ) : (
              <p className="m-0 text-[13px] text-muted">
                No boil-water notice is due or in force for {name}.
              </p>
            )}
          </>
        ) : (
          <NoticeBlock
            notice={notice}
            advisories={advisories.filter((a) => a.zone_id === zone.zone_id)}
            threshold={threshold}
            now={now}
            onOpenTab={onOpenTab}
          />
        )}
      </div>
    </div>
  );
}

export function ZonesContainer({ now, onOpenTab }: { now: string; onOpenTab?: (tab: WaterTab) => void }) {
  const zones = useZones();
  const cases = useWaterCases();
  const adv = useAdvisories();
  const policies = usePolicies();
  const list = (zones.data ?? []) as WaterZoneWithHistory[];
  const [focusZone] = useQueryState("zone", parseAsString);
  useFocusRow(
    focusZone,
    list.some((z) => z.zone_id === focusZone),
  );
  const threshold = policies.data?.find((p) => p.key === "policy_pre_landfall_breach_p")?.value;
  const notices = new Map(
    list.map((z) => [z.zone_id, noticeLifecycle(z, adv.data?.advisories ?? [], cases.allCards)] as const),
  );
  const openFirst = cases.isPending
    ? undefined
    : list.find((z) => isAbnormal(z, cases.cards, notices.get(z.zone_id)))?.zone_id;

  const columns: DataColumn<WaterZoneWithHistory>[] = [
    {
      id: "zone",
      header: "Zone",
      sort: (a, b) => zoneName(a.zone_id).localeCompare(zoneName(b.zone_id)),
      cell: (z) => (
        <span className="flex items-baseline gap-2">
          <span className="text-[14px] font-semibold">{zoneName(z.zone_id)}</span>
          <span className="text-[12px] whitespace-nowrap text-muted">{z.pump_station_id}</span>
        </span>
      ),
    },
    {
      id: "pressure",
      header: "Pressure now (psi)",
      sort: (a, b) => a.pressure_psi_x10 - b.pressure_psi_x10,
      cell: (z) => {
        const below = z.pressure_psi_x10 < z.floor_psi_x10;
        const history = z.pressure_history_psi_x10;
        return (
          <span className="flex items-center gap-3">
            <PressureBar psi={z.pressure_psi_x10 / 10} floorPsi={z.floor_psi_x10 / 10} />
            <span className="min-w-[96px]">
              <span className="block text-[14px] font-semibold tnum">{psi(z.pressure_psi_x10)}</span>
              {below && (
                <StatusText
                  level="severe"
                  label={`Below minimum (${psi(z.floor_psi_x10)})`}
                  className="text-[12px]"
                />
              )}
            </span>
            {history && history.length >= 2 && (
              <Sparkline
                values={history.map((v) => v / 10)}
                range={[50, 70]}
                width={56}
                height={22}
                label={`Pressure in ${zoneName(z.zone_id)}, last 6 h`}
                tone={below ? "warn" : "neutral"}
              />
            )}
          </span>
        );
      },
    },
    {
      id: "backup",
      header: "Backup power",
      cell: (z) => {
        const backup = backupPower(z, generatorOrdered(z.pump_station_id, cases.allCards));
        return backup.warn ? (
          <StatusText level="elevated" label={backup.label} className="text-[13px]" />
        ) : (
          <span className="block text-[13px] text-muted">{backup.label}</span>
        );
      },
    },
    {
      id: "notice",
      header: "Boil-water notice",
      className: "w-[150px]",
      cell: (z) => {
        const n = notices.get(z.zone_id);
        return n ? (
          <StatusText
            level={n.status.level}
            label={n.status.label}
            className="items-start text-[13px] leading-[18px] whitespace-normal [&>svg]:mt-[2px]"
          />
        ) : (
          <span className="text-[13px] text-muted">None</span>
        );
      },
    },
    {
      id: "next",
      header: "Next decision",
      cell: (z) => {
        const next = nextDecision(z, cases.cards);
        return next ? (
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[13px] leading-[18px] font-medium">{decisionTitle(next.title)}</span>
            <ClockText at={next.effective_decide_by_utc} now={now} className="text-[12px]" />
          </span>
        ) : (
          <span className="text-[13px] text-muted">No open decision</span>
        );
      },
    },
  ];

  if (zones.error) {
    return (
      <LoadFailed
        thing="pressure zones"
        icon={Droplets}
        error={zones.error}
        onRetry={() => void zones.refetch()}
      />
    );
  }
  if (zones.isPending) return <LoadingState label="Loading pressure zones…" rows={4} />;
  if (list.length === 0) return <EmptyState icon={Droplets} title="No pressure zones in this scenario." />;
  return (
    <DataTable
      caption="Pressure zones"
      data={list}
      columns={columns}
      getRowId={(z) => z.zone_id}
      rowTestId="zone-row"
      defaultExpanded={(z) => (focusZone ? z.zone_id === focusZone : z.zone_id === openFirst)}
      renderExpanded={(z) => (
        <ZoneDetail
          zone={z}
          cards={cases.cards}
          notice={notices.get(z.zone_id)}
          advisories={adv.data?.advisories ?? []}
          advisoriesError={adv.error}
          threshold={typeof threshold === "number" ? threshold : undefined}
          now={now}
          onOpenTab={onOpenTab}
        />
      )}
      edge
      compact
      className={cn("overflow-x-auto", FOCUS_ROW_CLASS)}
    />
  );
}
