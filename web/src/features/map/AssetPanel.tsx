import { AlertTriangle, MapPinned, X } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { ClockText, Tag } from "@/components/sgw";
import { IconButton } from "@/components/ui/icon-button";
import { decisionTitle } from "@/features/decisions/actionTypes";
import type { Asset, ProposalCard } from "@/lib/api";
import { cn } from "@/lib/cn";
import { assetName } from "@/lib/names";
import { ViewDecisionLink } from "../decisions/DecisionLink";
import { OPEN_STATES } from "../decisions/severity";
import { backupPower, generatorOrdered } from "../water/format";
import { useZones } from "../water/useWater";
import { placeIdsOf } from "./chain";

const KIND: Record<string, string> = {
  substation: "Substation",
  pump_station: "Pump station",
  staging_yard: "Staging yard",
  depot: "Depot",
  fuel_depot: "Fuel depot",
  critical_customer: "Hospital",
  portable_generator: "Portable generator",
  pressure_zone: "Pressure zone",
  hospital: "Hospital",
  feeder: "Feeder",
  shelter: "Shelter",
  care_home: "Care home",
  dialysis_center: "Dialysis center",
  dispatch_center: "911 center",
  treatment_plant: "Water treatment plant",
  lift_station: "Lift station",
  distribution_point: "Water distribution point",
  fuel_truck: "Fuel truck",
  potable_water_tanker: "Water tanker",
  chemical_truck: "Chemical truck",
};

interface Props {
  assets: Asset[];
  cards: ProposalCard[];
  now: string;
  onClose: () => void;
}

/** Flat side panel for the asset under the last map click: pressure, backup power and the open decisions here. */
export function AssetPanel({ assets, cards, now, onClose }: Props) {
  const zones = useZones().data ?? [];
  const ids = assets.map((a) => a.asset_id);
  const zone = zones.find(
    (z) =>
      ids.includes(z.pump_station_id) ||
      ids.includes(z.zone_id) ||
      z.critical_facility_ids.some((f) => ids.includes(f)),
  );
  const backup = zone ? backupPower(zone, generatorOrdered(zone.pump_station_id, cards)) : null;
  const here = useMemo(
    () =>
      cards
        .filter((c) => OPEN_STATES.has(c.state) && placeIdsOf(c).some((t) => ids.includes(t)))
        .sort((a, b) => Date.parse(a.effective_decide_by_utc) - Date.parse(b.effective_decide_by_utc)),
    [cards, ids],
  );
  const first = assets[0];
  if (!first) return null;
  const pressure = zone ? zone.pressure_psi_x10 / 10 : null;
  const floor = zone ? zone.floor_psi_x10 / 10 : null;
  const max = floor ? floor * 3 : 1;
  return (
    <section aria-label="Selected asset" data-testid="asset-panel" className="flex flex-col">
      <header className="flex items-start gap-2 border-b border-hair px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="m-0 flex items-center gap-2 text-[12px] text-muted">
            <MapPinned className="size-3.5" aria-hidden />
            {KIND[first.kind] ?? first.kind.replace(/_/g, " ")}
            <Tag domain={first.domain === "water" ? "water" : "power"}>
              {first.domain === "water" ? "Water" : "Power"}
            </Tag>
          </p>
          <h2 title={first.asset_id} className="m-0 mt-1 text-[16px] leading-6 font-bold">
            {first.name ?? assetName(first.asset_id)}
          </h2>
        </div>
        <IconButton small label="Close details" icon={<X />} onClick={onClose} />
      </header>
      <dl className="m-0 flex flex-col gap-4 px-5 py-4 text-[13px]">
        {first.customers_served > 0 && (
          <div>
            <dt className="text-[12px] font-semibold text-muted">Customers served</dt>
            <dd className="m-0 text-[15px] font-semibold tnum">
              {first.customers_served.toLocaleString("en-US")}
            </dd>
          </div>
        )}
        {zone && pressure !== null && floor !== null && (
          <div>
            <dt className="text-[12px] font-semibold text-muted">Pressure in {assetName(zone.zone_id)}</dt>
            <dd className="m-0">
              <span className="text-[15px] font-semibold tnum">{pressure.toFixed(1)} psi</span>
              <span className="ml-2 text-muted">floor {floor} psi</span>
              <span
                role="img"
                aria-label={`Pressure ${pressure.toFixed(1)} psi against a floor of ${floor} psi`}
                className="relative mt-1.5 block h-2 rounded-full bg-track"
              >
                <span
                  className="absolute inset-y-0 left-0 rounded-full bg-[var(--chart-1)]"
                  style={{ width: `${Math.min(100, (pressure / max) * 100)}%` }}
                />
                <span
                  aria-hidden
                  className="absolute -top-0.5 h-3 w-0.5 bg-ink"
                  style={{ left: `${(floor / max) * 100}%` }}
                />
              </span>
            </dd>
          </div>
        )}
        {zone && (
          <div>
            <dt className="text-[12px] font-semibold text-muted">Backup power</dt>
            <dd
              data-testid="asset-backup-power"
              className={cn(
                "m-0 flex items-center gap-1.5 font-medium",
                backup?.warn ? "text-warn" : "text-ink",
              )}
            >
              {backup?.warn && <AlertTriangle className="size-3.5" aria-hidden />}
              {backup?.label}
            </dd>
          </div>
        )}
      </dl>
      <section aria-labelledby="open-here" className="border-t border-hair px-5 py-4">
        <h3 id="open-here" className="m-0 mb-2 text-[15px] leading-5 font-bold">
          Open decisions here
        </h3>
        {here.length === 0 ? (
          <p className="m-0 text-[13px] text-muted">No open decisions at this asset.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {here.map((c) => (
              <li
                key={c.proposal_id}
                className="flex flex-col gap-1 border-b border-hair py-3 last:border-b-0"
              >
                <span className="text-[14px] leading-[18px] font-medium">{decisionTitle(c.title)}</span>
                <span className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
                  <ViewDecisionLink proposalId={c.proposal_id} className="justify-self-start" />
                  <ClockText at={c.effective_decide_by_utc} now={now} column />
                </span>
              </li>
            ))}
          </ul>
        )}
        {zone && (
          <Link
            to="/water"
            className="mt-2 inline-block text-[13px] font-semibold text-blue-ink hover:underline"
          >
            See in Water
          </Link>
        )}
      </section>
    </section>
  );
}
