import { Sparkline } from "@/components/sgw";
import type { ProposalCard } from "@/lib/api";
import { cn } from "@/lib/cn";
import { zoneName } from "@/lib/names";
import { useAdvisories, useZones } from "../water/useWater";
import { usePolicies } from "./queries";

const pct = (ppm: number) => `${(ppm / 10_000).toFixed(1)}%`;

function Row({
  label,
  line,
  value,
  spark,
  warn,
}: {
  label: string;
  line: string;
  value: string;
  spark?: React.ReactNode;
  warn?: boolean;
}) {
  return (
    <li className="flex items-center gap-3 border-b border-hair py-1.5 first:border-t">
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[13px] leading-[18px] text-ink-2">{label}</p>
        <p className="m-0 text-[12px] leading-4 text-muted">{line}</p>
      </div>
      {spark}
      <span className={cn("w-[72px] shrink-0 text-end text-[15px] font-semibold tnum", warn && "text-warn")}>
        {value}
      </span>
    </li>
  );
}

/**
 * What to keep an eye on while deciding: the pressure at the zone this decision protects and, when a boil-water
 * assessment exists for it, how the chance changed from one advisory to the next. A line is drawn only where a real
 * history exists: the zone feed gives the current pressure only, so that row has no sparkline.
 */
export function WatchRows({ card }: { card: ProposalCard }) {
  const zones = useZones().data ?? [];
  const advisories = useAdvisories().data?.advisories ?? [];
  const trigger = usePolicies().data?.find((p) => p.key === "policy_pre_landfall_breach_p")?.value;
  const zone = zones.find(
    (z) =>
      card.target_ids.includes(z.pump_station_id) ||
      card.target_ids.includes(z.zone_id) ||
      z.critical_facility_ids.some((f) => card.target_ids.includes(f)),
  );
  const advisory = advisories.find(
    (a) => a.decision_case_id === card.decision_case_id || (zone && a.zone_id === zone.zone_id),
  );
  const series = advisory?.assessments.map((a) => a.breach_p_ppm) ?? [];
  const last = series.at(-1);
  if (!zone && !advisory) return null;
  const over = typeof trigger === "number" && last !== undefined && last / 1_000_000 > trigger;
  return (
    <ul className="m-0 list-none p-0" aria-label="What to watch" data-testid="watch-rows">
      {zone && (
        <Row
          label={`Pressure in ${zoneName(zone.zone_id)}`}
          line={`Now, floor ${zone.floor_psi_x10 / 10} psi`}
          value={`${(zone.pressure_psi_x10 / 10).toFixed(1)} psi`}
        />
      )}
      {advisory && last !== undefined && (
        <Row
          label="Chance of low pressure"
          line={`${series.length > 1 ? "Previous → latest" : "Latest advisory"}${typeof trigger === "number" ? `, trigger ${Math.round(trigger * 100)}%` : ""}`}
          value={pct(last)}
          warn={over}
          spark={
            series.length > 1 ? (
              <Sparkline
                values={series}
                width={72}
                height={24}
                tone={over ? "warn" : "neutral"}
                label="Chance of low pressure, previous to latest advisory"
              />
            ) : undefined
          }
        />
      )}
    </ul>
  );
}
