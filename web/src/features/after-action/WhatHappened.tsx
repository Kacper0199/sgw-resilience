import { useQuery } from "@tanstack/react-query";
import { CloudLightning } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, KeyNumberStrip, LoadingState } from "@/components/sgw";
import type { components } from "@/contracts/api.gen";
import { get } from "@/lib/api";
import { formatDayET, formatET } from "@/lib/time";
import { FLUSH } from "./parts";

export type OfficialRecord = components["schemas"]["OfficialRecord"];
type Declaration = components["schemas"]["DisasterDeclaration"];
type StormEvent = components["schemas"]["StormEventItem"];

const FOOTPRINT_COUNTIES = 123;
const SHOWN_EVENTS = 5;
const NCEI = "https://www.ncdc.noaa.gov/stormevents/";
const femaUrl = (id: string) => `https://www.fema.gov/disaster/${id.split("-")[1]}`;

export const useOfficialRecord = () =>
  useQuery({
    queryKey: ["after-action", "official-record"],
    queryFn: () => get<OfficialRecord>("/api/after-action/official-record"),
    staleTime: 60_000,
    retry: false,
  });

const TYPE_LABEL: Record<string, string> = {
  "Hurricane (Typhoon)": "Hurricane",
  "Thunderstorm Wind": "Storm wind",
};
const typeLabel = (t: string) => TYPE_LABEL[t] ?? t;

export function money(usd: number): string {
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)} B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(usd >= 1e7 ? 0 : 1)} M`;
  if (usd >= 1e3) return `$${Math.round(usd / 1e3)} K`;
  return usd > 0 ? `$${usd}` : "—";
}

export function declaredCounties(record: OfficialRecord): number {
  return new Set(record.declarations.flatMap((d) => d.footprint_counties)).size;
}

const day = (date: string) => formatDayET(`${date}T12:00:00Z`);

const declarationColumns: DataColumn<Declaration>[] = [
  {
    id: "id",
    header: "Declaration",
    cell: (d) => (
      <a
        href={femaUrl(d.declaration_id)}
        target="_blank"
        rel="noreferrer"
        className="font-mono text-[13px] text-blue-ink hover:underline"
      >
        {d.declaration_id}
      </a>
    ),
  },
  {
    id: "declared",
    header: "Declared",
    className: "whitespace-nowrap tnum",
    cell: (d) => day(d.declared_on),
  },
  {
    id: "counties",
    header: "Our counties",
    align: "end",
    className: "tnum",
    cell: (d) => (
      <>
        {d.footprint_counties.length}
        <span className="text-muted"> of {d.counties_total}</span>
      </>
    ),
  },
  {
    id: "programs",
    header: "Programs",
    cell: (d) => <span className="text-[13px]">{d.programs.join(", ")}</span>,
  },
];

const eventColumns: DataColumn<StormEvent>[] = [
  {
    id: "event",
    header: "Event",
    cell: (e) => (
      <a href={e.url} target="_blank" rel="noreferrer" className="text-blue-ink hover:underline">
        {typeLabel(e.event_type)}
      </a>
    ),
  },
  { id: "where", header: "County", cell: (e) => `${e.county}, ${e.state}` },
  {
    id: "began",
    header: "Began",
    className: "whitespace-nowrap tnum",
    cell: (e) => `${formatDayET(e.begin_utc)}, ${formatET(e.begin_utc)}`,
  },
  { id: "deaths", header: "Deaths", align: "end", className: "tnum", cell: (e) => e.deaths || "—" },
  { id: "damage", header: "Damage", align: "end", className: "tnum", cell: (e) => money(e.damage_usd) },
];

/** What happened, from the official records: federal declarations and NOAA storm reports in the service area, up to
 * the scenario time. Numbers first; each row links to its official page. */
export function WhatHappened({ record }: { record: OfficialRecord }) {
  const declared = declaredCounties(record);
  return (
    <div className="flex flex-col gap-5" data-testid="what-happened">
      <KeyNumberStrip
        className="border-b border-hair px-0 pt-0 pb-4"
        items={[
          {
            label: "Federal declarations",
            value: record.declarations.length,
            line:
              record.declarations.length > 0
                ? record.declarations.map((d) => d.state).join(", ")
                : "None yet",
          },
          {
            label: "Our counties declared",
            value: declared,
            line: `of ${FOOTPRINT_COUNTIES}`,
          },
          {
            label: "Storm reports",
            value: record.events_total,
            line: "NOAA Storm Events",
          },
          {
            label: "Deaths reported",
            value: record.deaths,
            line: "Direct and indirect",
          },
          {
            label: "Property damage",
            value: money(record.damage_usd),
            line: "As reported",
          },
        ]}
      />
      {record.declarations.length > 0 ? (
        <DataTable
          data={record.declarations}
          columns={declarationColumns}
          getRowId={(d) => d.declaration_id}
          caption="FEMA major disaster declarations"
          rowTestId="declaration-row"
          className={FLUSH}
        />
      ) : (
        <p className="m-0 text-[13px] text-muted">No federal disaster declaration yet.</p>
      )}
      {record.events_total > 0 && (
        <div className="flex flex-col gap-2">
          <ul
            className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-[13px]"
            aria-label="Storm reports by type"
          >
            {record.events_by_type.map((t) => (
              <li key={t.event_type}>
                {typeLabel(t.event_type)} <span className="font-semibold tnum">{t.count}</span>
              </li>
            ))}
          </ul>
          {record.top_events.length > 0 && (
            <>
              <h3 className="m-0 mt-2 text-[12px] font-semibold text-muted">Most severe</h3>
              <DataTable
                data={record.top_events.slice(0, SHOWN_EVENTS)}
                columns={eventColumns}
                getRowId={(e) => String(e.event_id)}
                caption="Most severe storm reports"
                rowTestId="storm-event-row"
                className={FLUSH}
              />
            </>
          )}
        </div>
      )}
      <p className="m-0 text-[12px] leading-[18px] text-muted">
        Sources: FEMA OpenFEMA, NOAA{" "}
        <a href={NCEI} target="_blank" rel="noreferrer" className="text-blue-ink underline">
          Storm Events Database
        </a>
        . Published after the event; shown up to the scenario time. {record.attribution[0]}
      </p>
    </div>
  );
}

/** The section body with its own loading and error states, so the rest of the review never waits on it. */
export function WhatHappenedSection() {
  const record = useOfficialRecord();
  if (record.isPending) return <LoadingState rows={2} label="Loading the official record…" />;
  if (record.isError || !record.data)
    return <EmptyState icon={CloudLightning} title="The official record isn't available." />;
  return <WhatHappened record={record.data} />;
}
