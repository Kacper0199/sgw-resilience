import { Waypoints } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { Container, EmptyState } from "@/components/sgw";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { decisionHref } from "@/lib/links";
import { assetName } from "@/lib/names";
import { usePhase } from "@/lib/PhaseProvider";
import { forecastIsHistory } from "@/lib/phase";
import { isPack } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import { OPEN_STATES } from "../decisions/severity";
import { useQueue } from "../decisions/useQueue";
import { useZones } from "../water/useWater";
import { useAssets, useCountyRisk, useRegions } from "./data";
import { BAND_WORDS, facilityDecisions, summariseLifelines } from "./lifelineSummary";

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

/** Open decisions that act on a facility, else those on the pump station that serves it. */
function OpenHere({ assetId }: { assetId: string }) {
  const { items } = useQueue();
  const zones = useZones().data ?? [];
  const stations = zones
    .filter((z) => z.critical_facility_ids.includes(assetId))
    .map((z) => z.pump_station_id);
  const here = facilityDecisions(
    assetId,
    stations,
    items.filter((i) => OPEN_STATES.has(i.summary.state)),
  );
  if (here.length === 0) return <span className="block text-label text-muted">No open decisions here</span>;
  return (
    <span className="mt-0.5 flex flex-col gap-0.5" data-testid="facility-decisions">
      <span className="text-label text-muted">Open decisions here</span>
      {here.map((i) => (
        <Link
          key={i.summary.proposal_id}
          to={decisionHref(i.summary.proposal_id)}
          className="text-[13px] font-medium text-blue-ink hover:underline"
        >
          {decisionTitle(i.summary.title)}
        </Link>
      ))}
    </span>
  );
}

/** Lifelines summary: the services people depend on and how many sit in high-risk counties at this advisory, until the forecast is history. */
export function Lifelines({ asOf }: { asOf: string | null }) {
  const assets = useAssets();
  const regions = useRegions();
  const risk = useCountyRisk(asOf);
  const scripted = isPack(useScenario().data?.scenario);
  const history = forecastIsHistory(usePhase()) || scripted;
  const summary = useMemo(
    () => summariseLifelines(assets.data ?? [], regions.data ?? [], risk.data?.items ?? []),
    [assets.data, regions.data, risk.data],
  );
  const loading = assets.isPending || regions.isPending;
  const failed = assets.isError || regions.isError;

  return (
    <Container title="Lifelines" info="lifelines" bodyClassName="overflow-auto">
      {loading ? (
        <Skeleton className="m-4 h-32" />
      ) : failed ? (
        <EmptyState icon={Waypoints} title="Lifelines aren't available yet." />
      ) : (
        <div className="flex flex-col gap-4 p-4" data-testid="lifelines">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Service</TableHead>
                <TableHead className="text-right">Count</TableHead>
                {!history && <TableHead className="text-right">In high-risk counties</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.rows.map((r) => (
                <TableRow key={r.key}>
                  <TableCell>{r.label}</TableCell>
                  <TableCell className="text-right tnum">{r.total}</TableCell>
                  {!history && (
                    <TableCell className="text-right tnum">{risk.data ? r.highRisk : "–"}</TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <section aria-labelledby="critical-facilities">
            <h3 id="critical-facilities" className="m-0 mb-1.5 text-[13px] font-semibold">
              Critical facilities
            </h3>
            <ul className="m-0 flex list-none flex-col p-0">
              {summary.critical.map((f) => (
                <li
                  key={f.assetId}
                  className="flex items-center justify-between gap-3 border-b border-hair py-2 text-[13px] last:border-b-0"
                >
                  <span className="min-w-0">
                    <span title={f.assetId}>{assetName(f.assetId)}</span>
                    <span className="block text-label text-muted">
                      {KIND[f.kind] ?? f.kind} in {f.county} County
                    </span>
                    <OpenHere assetId={f.assetId} />
                  </span>
                  {f.band && !history && (
                    <span className="shrink-0 text-[12px] text-ink-2">{BAND_WORDS[f.band]} outage risk</span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </Container>
  );
}
