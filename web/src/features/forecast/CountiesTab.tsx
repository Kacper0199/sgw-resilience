import { TriangleAlert } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { useMemo } from "react";
import {
  type DataColumn,
  DataTable,
  EmptyState,
  LoadingState,
  Section,
  SegmentedControl,
} from "@/components/sgw";
import { isMissing, loadFailureTitle } from "@/lib/loadFailure";
import { useCountyForecast } from "./data";
import { FanChart } from "./FanChart";
import { count, countyLabel } from "./format";
import type { CountyFan } from "./types";
import { WhatIfTab } from "./WhatIfTab";

const TOP = 12;

const COLUMNS: DataColumn<CountyFan>[] = [
  {
    id: "county",
    header: "County",
    cell: (c) => <span className="font-medium">{countyLabel(c.name, c.fips)}</span>,
    sort: (a, b) => a.name.localeCompare(b.name),
  },
  {
    id: "median",
    header: "Median",
    align: "end",
    cell: (c) => <span className="tnum">{count(c.q0500)}</span>,
    sort: (a, b) => a.q0500 - b.q0500,
  },
  {
    id: "range",
    header: "80% range",
    align: "end",
    className: "whitespace-nowrap",
    cell: (c) => (
      <span className="tnum">
        {count(c.q0100)} to {count(c.q0900)}
      </span>
    ),
    sort: (a, b) => a.q0900 - b.q0900,
  },
];

const ACTUAL: DataColumn<CountyFan> = {
  id: "actual",
  header: "Actual",
  align: "end",
  className: "whitespace-nowrap",
  cell: (c) => <span className="tnum">{c.observed_peak == null ? "–" : count(c.observed_peak)}</span>,
  sort: (a, b) => (a.observed_peak ?? 0) - (b.observed_peak ?? 0),
};

const VIEWS = ["range", "whatif"] as const;

export function CountiesTab({ advisory, observed = false }: { advisory: string | null; observed?: boolean }) {
  const [view, setView] = useQueryState("view", parseAsStringLiteral(VIEWS).withDefault("range"));
  const forecast = useCountyForecast(advisory);
  const top = useMemo(
    () => [...(forecast.data?.counties ?? [])].sort((a, b) => b.q0900 - a.q0900).slice(0, TOP),
    [forecast.data],
  );

  const toggle = (
    <div className="px-8 pt-4">
      <SegmentedControl
        label="Outages view"
        value={view}
        onValueChange={(v) => void setView(v)}
        options={[
          { value: "range", label: "Counties" },
          { value: "whatif", label: "What-ifs" },
        ]}
      />
    </div>
  );
  if (view === "whatif") {
    return (
      <div data-testid="counties-tab">
        {toggle}
        <WhatIfTab />
      </div>
    );
  }
  if (forecast.isPending && advisory !== null) {
    return <LoadingState rows={6} label="Loading the county forecast" className="px-8 pt-4" />;
  }
  if (forecast.error && !isMissing(forecast.error)) {
    return (
      <EmptyState
        role="alert"
        icon={TriangleAlert}
        title={loadFailureTitle(forecast.error, "the county forecast")}
      />
    );
  }
  if (!forecast.data) {
    return <EmptyState icon={TriangleAlert} title="No county forecast for this advisory yet." />;
  }
  return (
    <div data-testid="counties-tab">
      {toggle}
      <Section
        className="px-8 pt-4"
        title={
          observed
            ? `Forecast vs actual: the ${TOP} counties forecast to be hit hardest`
            : `Customers without power at the peak: the ${TOP} counties at most risk`
        }
        info="fan"
      >
        <div className="grid items-start gap-x-8 gap-y-4 min-[1280px]:grid-cols-[minmax(0,1fr)_380px]">
          <FanChart counties={top} />
          <DataTable
            compact
            caption="County ranges in customers"
            data={top}
            getRowId={(c) => c.fips}
            columns={observed ? [...COLUMNS, ACTUAL] : COLUMNS}
          />
        </div>
      </Section>
    </div>
  );
}
