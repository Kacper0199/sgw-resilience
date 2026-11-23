import { Thermometer, TriangleAlert } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, LoadingState, StatusText, Tag } from "@/components/sgw";
import { cn } from "@/lib/cn";
import { assetName } from "@/lib/names";
import { formatET } from "@/lib/time";
import { ActionPane } from "./ActionPane";
import { HeatChart } from "./HazardCharts";
import { HazardInfo, OriginTag } from "./HazardInfo";
import { BlockHeading, Fact, HazardLayout, Summary } from "./HazardLayout";
import { ALARM, dayET, unitsInWarning, windowText } from "./hazardModel";
import type { HeatView as Heat, HeatUnit } from "./hazardTypes";
import { useHeatLibrary } from "./useHazardLibrary";

const at = (iso: string) => `${dayET(iso)}, ${formatET(iso)}`;

const COLUMNS: DataColumn<HeatUnit>[] = [
  {
    id: "unit",
    header: "Unit",
    cell: (u) => (
      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span>{assetName(u.asset_id)}</span>
        {u.protected_load && <Tag>Critical load</Tag>}
      </span>
    ),
  },
  {
    id: "peak",
    header: "Peak hot spot",
    align: "end",
    cell: (u) => (
      <span className="text-[13px] font-semibold tnum whitespace-nowrap">
        {u.peak_hot_spot_c.toFixed(0)} °C
      </span>
    ),
  },
  {
    id: "hours",
    header: "Hours ≥ 120 °C",
    align: "end",
    cell: (u) => <span className="text-[13px] tnum">{u.hours_ge_120c.toFixed(0)}</span>,
  },
  {
    id: "aging",
    header: "Ageing",
    align: "end",
    cell: (u) => (
      <span className="text-[13px] tnum whitespace-nowrap">{u.aging_equiv_days.toFixed(1)} d</span>
    ),
  },
  {
    id: "status",
    header: "Status",
    cell: (u) => <StatusText {...ALARM[u.alarm]} className="text-[13px]" />,
  },
];

function HeatBody({ view }: { view: Heat }) {
  const warn = unitsInWarning(view);
  const over = view.line.still_air_peak_loading_pct > 100;
  return (
    <>
      <Summary testId="heat-summary">
        <span className="text-muted">{windowText(view.window_start_utc, view.window_end_utc)}</span>
        <span>
          Trigger <b className="font-semibold tnum">{view.threshold_c.toFixed(1)} °C</b>
        </span>
        <span className={cn(warn > 0 && "text-warn")}>
          <b className="font-semibold tnum">{warn}</b> of {view.units.length} units in warning
        </span>
        <span className={cn(over && "text-warn")}>
          <b className="font-semibold tnum">{view.line.still_air_peak_loading_pct.toFixed(0)}%</b> line load
          in still air
        </span>
      </Summary>
      <BlockHeading
        title={`Daily high, mean of ${view.stations.length} stations`}
        tag={<OriginTag origin="real" />}
      />
      <div className="px-6">
        <HeatChart view={view} height={168} />
      </div>
      <BlockHeading title="Transformer hot spots" tag={<OriginTag origin="synthetic" />} />
      <DataTable
        caption="Transformer hot spots"
        data={view.units}
        getRowId={(u) => u.asset_id}
        rowTestId="heat-unit-row"
        columns={COLUMNS}
        compact
        edge
      />
    </>
  );
}

function HeatAction({ view }: { view: Heat }) {
  const line = view.line;
  return (
    <ActionPane actions={view.actions} appliesTo={assetName(line.feeder_id)} asOf={at(view.as_of)}>
      <h3 className="m-0 mt-5 border-b border-hair pb-2 text-[15px] leading-5 font-bold">Why</h3>
      <dl className="m-0 mt-3 grid grid-cols-2 gap-x-6 gap-y-3" data-testid="heat-line-check">
        <Fact label="Line load, still air">
          <span className="text-warn tnum">{line.still_air_peak_loading_pct.toFixed(0)}%</span>
        </Fact>
        <Fact label="At rating wind">
          <span className="tnum">{line.rating_wind_peak_loading_pct.toFixed(0)}%</span>
        </Fact>
        <Fact label="Line limit reached">
          {line.line_limit_utc ? at(line.line_limit_utc) : "Not reached"}
        </Fact>
        <Fact label="Before transformer warning">
          <span className="tnum">{line.line_leads_transformer_h.toFixed(0)} h</span>
        </Fact>
      </dl>
    </ActionPane>
  );
}

export function HeatView() {
  const q = useHeatLibrary();
  const view = q.data;
  return (
    <HazardLayout
      id="heat"
      sources={view && <HazardInfo sources={view.sources} asOf={at(view.as_of)} />}
      action={view ? <HeatAction view={view} /> : undefined}
    >
      {q.isPending ? (
        <LoadingState rows={5} label="Loading the heat wave…" className="px-8" />
      ) : q.error || !view ? (
        <EmptyState role="alert" icon={TriangleAlert} title="Couldn't load the heat wave." />
      ) : view.days.length === 0 ? (
        <EmptyState icon={Thermometer} title="No heat wave data." />
      ) : (
        <HeatBody view={view} />
      )}
    </HazardLayout>
  );
}
