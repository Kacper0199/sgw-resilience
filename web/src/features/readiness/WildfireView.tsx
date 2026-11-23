import { Flame, TriangleAlert } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, LoadingState } from "@/components/sgw";
import { assetName } from "@/lib/names";
import { formatET } from "@/lib/time";
import { ActionPane } from "./ActionPane";
import { FireChart } from "./HazardCharts";
import { HazardInfo, OriginTag } from "./HazardInfo";
import { BlockHeading, Fact, HazardLayout, Summary } from "./HazardLayout";
import { dayET, peakIndex, percent, redFlagHours, windowText } from "./hazardModel";
import type { CircuitRisk, WildfireView as Fire } from "./hazardTypes";
import { useWildfireLibrary } from "./useHazardLibrary";

const at = (iso: string) => `${dayET(iso)}, ${formatET(iso)}`;
const count = new Intl.NumberFormat("en-US");

const COLUMNS: DataColumn<CircuitRisk>[] = [
  {
    id: "rank",
    header: "#",
    cell: (c) => <span className="text-[13px] text-muted tnum">{c.rank}</span>,
  },
  {
    id: "circuit",
    header: "Circuit",
    cell: (c) => (
      <span className="flex items-baseline gap-2 whitespace-nowrap">
        <span>{assetName(c.feeder_id)}</span>
        <span className="text-[12px] text-muted">{c.county}</span>
      </span>
    ),
  },
  {
    id: "customers",
    header: "Customers",
    align: "end",
    cell: (c) => <span className="text-[13px] tnum">{count.format(c.customers)}</span>,
  },
  {
    id: "chance",
    header: "Ignition chance",
    align: "end",
    cell: (c) => <span className="text-[13px] font-semibold tnum">{percent(c.p_ignition_window)}</span>,
  },
  {
    id: "ratio",
    header: "vs average",
    align: "end",
    cell: (c) => <span className="text-[13px] tnum">{c.ratio_to_average_window.toFixed(1)}×</span>,
  },
];

function FireBody({ view }: { view: Fire }) {
  return (
    <>
      <Summary testId="wildfire-summary">
        <span className="text-muted">{windowText(view.window_start_utc, view.window_end_utc)}</span>
        <span className="text-warn">
          <b className="font-semibold tnum">{view.episodes.length}</b> Red Flag periods,{" "}
          <span className="tnum">{redFlagHours(view)} h</span>
        </span>
        <span>
          Fire index peak <b className="font-semibold tnum">{peakIndex(view).toFixed(0)}</b>
        </span>
        <span>
          <b className="font-semibold tnum">{view.expected_ignitions_all.toFixed(2)}</b> expected ignitions
        </span>
      </Summary>
      <BlockHeading
        title={`Hourly fire weather index at ${view.station}`}
        tag={<OriginTag origin="real" />}
      />
      <div className="px-6">
        <FireChart view={view} height={132} />
      </div>
      <BlockHeading
        title={`Highest ignition risk, top ${view.circuits.length} of ${view.circuits_total}`}
        tag={<OriginTag origin="synthetic" />}
      />
      <DataTable
        caption="Circuits with the highest ignition risk"
        data={view.circuits}
        getRowId={(c) => c.feeder_id}
        rowTestId="wildfire-circuit-row"
        columns={COLUMNS}
        compact
        edge
        className="[&_td]:py-0 [&_tr[data-row]]:h-7"
      />
    </>
  );
}

function FireAction({ view }: { view: Fire }) {
  const first = view.actions[0];
  return (
    <ActionPane
      actions={view.actions}
      appliesTo={first ? `Top ${view.circuits.length} circuits` : ""}
      asOf={at(view.as_of)}
    >
      <h3 className="m-0 mt-5 border-b border-hair pb-2 text-[15px] leading-5 font-bold">Why</h3>
      <dl className="m-0 mt-3 grid grid-cols-2 gap-x-6 gap-y-3" data-testid="wildfire-why">
        <Fact label="Trigger">
          <span className="tnum">
            Index ≥ {view.ffwi_min.toFixed(0)}, humidity ≤ {view.rh_max_pct.toFixed(0)}%
          </span>
        </Fact>
        <Fact label="First Red Flag">{view.episodes[0] ? at(view.episodes[0].start_utc) : "None"}</Fact>
        {view.fires.map((f) => (
          <Fact key={f.name} label={`${f.name}, ${f.county}`}>
            <span className="tnum">
              {dayET(f.discovered_utc)}, {count.format(f.acres)} acres
            </span>
          </Fact>
        ))}
      </dl>
    </ActionPane>
  );
}

export function WildfireView() {
  const q = useWildfireLibrary();
  const view = q.data;
  return (
    <HazardLayout
      id="wildfire"
      sources={view && <HazardInfo sources={view.sources} asOf={at(view.as_of)} />}
      action={view ? <FireAction view={view} /> : undefined}
    >
      {q.isPending ? (
        <LoadingState rows={6} label="Loading the fire weather…" className="px-8" />
      ) : q.error || !view ? (
        <EmptyState role="alert" icon={TriangleAlert} title="Couldn't load the fire weather." />
      ) : view.hours.length === 0 ? (
        <EmptyState icon={Flame} title="No fire weather data." />
      ) : (
        <FireBody view={view} />
      )}
    </HazardLayout>
  );
}
