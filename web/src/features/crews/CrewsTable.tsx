import { Users } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { useMe } from "@/auth/useSession";
import { type DataColumn, DataTable, EmptyState, LoadingState, StatusText } from "@/components/sgw";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { LoadFailed } from "@/features/water/LoadFailed";
import { decisionPageHref } from "@/lib/links";
import { crewName } from "@/lib/names";
import { formatDayET, formatEtZ } from "@/lib/time";
import { useScenario } from "@/sse/useScenarioNow";
import { CrewMenu } from "./CrewMenu";
import { BLOCK_REASON, crewStatusLabel } from "./dispatch";
import { int, placeName } from "./format";
import type { CrewItem } from "./types";
import { useCrewList } from "./useCrews";

function Status({ c }: { c: CrewItem }) {
  const me = useMe().data;
  if (c.status === "blocked") {
    return (
      <span className="flex flex-col leading-tight">
        <StatusText level="elevated" label="Blocked" className="text-[14px]" />
        {c.block_reason && <span className="text-[12px] text-muted">{BLOCK_REASON[c.block_reason]}</span>}
      </span>
    );
  }
  return <span data-state={c.assignment?.state}>{crewStatusLabel(c, me?.function)}</span>;
}

const FIELD_DISPATCHED = new Set(["enroute", "onsite"]);

/** An SGW assignment links to its decision; a crew the field system sent out names where it went. */
function AssignedTo({ c }: { c: CrewItem }) {
  const a = c.assignment;
  if (!a && FIELD_DISPATCHED.has(c.status) && c.location_id) {
    return (
      <span data-testid="crew-assigned" title="Sent there by the field system">
        {placeName(c.location_id)}
      </span>
    );
  }
  if (!a)
    return (
      <span data-testid="crew-assigned" className="text-muted">
        —
      </span>
    );
  if (a.target_kind === "decision" && a.decision_proposal_id) {
    return (
      <Link
        to={decisionPageHref(a.decision_proposal_id)}
        className="text-blue-ink hover:underline"
        title="Open this decision"
      >
        {decisionTitle(a.target_label)}
      </Link>
    );
  }
  return a.target_label;
}

const ALL_COLUMNS: DataColumn<CrewItem>[] = [
  {
    id: "crew",
    header: "Crew",
    sort: (a, b) => crewName(a.crew_id).localeCompare(crewName(b.crew_id)),
    cell: (c) => <span title={c.crew_id}>{crewName(c.crew_id)}</span>,
  },
  {
    id: "status",
    header: "Status",
    sort: (a, b) => crewStatusLabel(a).localeCompare(crewStatusLabel(b)),
    cell: (c) => <Status c={c} />,
  },
  {
    id: "assigned",
    header: "Assigned to",
    sort: (a, b) => (a.assignment?.target_label ?? "~").localeCompare(b.assignment?.target_label ?? "~"),
    cell: (c) => <AssignedTo c={c} />,
    className: "max-w-[360px] truncate",
  },
  {
    id: "location",
    header: "Location",
    sort: (a, b) => (a.location_id ?? "").localeCompare(b.location_id ?? ""),
    cell: (c) => (c.location_id ? placeName(c.location_id) : "—"),
  },
  {
    id: "people",
    header: "People",
    align: "end",
    sort: (a, b) => a.headcount - b.headcount,
    cell: (c) => <span className="tnum">{int(c.headcount)}</span>,
  },
  {
    id: "shift_end",
    header: "Shift ends",
    sort: (a, b) => (a.shift_end ?? "").localeCompare(b.shift_end ?? ""),
    cell: (c) =>
      c.shift_end ? (
        <span className="font-mono text-[12.5px] tnum">{formatEtZ(c.shift_end)}</span>
      ) : (
        <span className="text-muted">Not set</span>
      ),
  },
];

/** A report from an earlier day carries its day, so an 11-hour-old report never reads as today's. */
function ReportTime({ iso }: { iso: string }) {
  const now = useScenario().data?.scenario_time;
  const sameDay = !now || formatDayET(iso) === formatDayET(now);
  return (
    <span className="font-mono text-[12.5px] tnum">
      {sameDay ? formatEtZ(iso) : `${formatDayET(iso)} ${formatEtZ(iso)}`}
    </span>
  );
}

const REPORTED: DataColumn<CrewItem> = {
  id: "reported",
  header: "Last report",
  sort: (a, b) => (a.provenance?.as_of ?? "").localeCompare(b.provenance?.as_of ?? ""),
  cell: (c) =>
    c.provenance?.as_of ? (
      <ReportTime iso={c.provenance.as_of} />
    ) : (
      <span className="text-muted">No report</span>
    ),
};

const ACTIONS: DataColumn<CrewItem> = {
  id: "actions",
  header: <span className="sr-only">Actions</span>,
  align: "end",
  className: "w-12",
  cell: (c) => <CrewMenu crew={c} />,
};

/** A column nobody has data for is hidden; read-only personas get no action column at all. */
export function columnsFor(crews: CrewItem[]): DataColumn<CrewItem>[] {
  const hasLocation = crews.some((c) => c.location_id);
  const hasShift = crews.some((c) => c.shift_end);
  const hasReport = crews.some((c) => c.provenance?.as_of);
  const hasAssignment = crews.some((c) => c.assignment || FIELD_DISPATCHED.has(c.status));
  const canAct = crews.some((c) => (c.actions ?? []).length > 0);
  const cols = ALL_COLUMNS.flatMap((col) => {
    if (col.id === "location" && !hasLocation) return [];
    if (col.id === "assigned" && !hasAssignment && !canAct) return [];
    if (col.id === "shift_end" && !hasShift) return hasReport ? [REPORTED] : [];
    return [col];
  });
  return canAct ? [...cols, ACTIONS] : cols;
}

/** The crews tab: every crew with its status and assignment; `focus` (from `?crew=`) marks and scrolls to one row. */
export function CrewsTable({ focus }: { focus?: string | null }) {
  const q = useCrewList();
  const wrap = useRef<HTMLDivElement>(null);
  const ready = Boolean(q.data);
  useEffect(() => {
    if (!focus || !ready) return;
    const row = wrap.current?.querySelector<HTMLElement>(`tr[data-row-id="${CSS.escape(focus)}"]`);
    row?.scrollIntoView({ block: "center" });
  }, [focus, ready]);
  if (q.error)
    return <LoadFailed thing="the crew list" icon={Users} error={q.error} onRetry={() => void q.refetch()} />;
  if (q.isPending) return <LoadingState label="Loading crews…" rows={4} />;
  const crews = [...q.data].sort((a, b) => crewName(a.crew_id).localeCompare(crewName(b.crew_id)));
  if (crews.length === 0) {
    return <EmptyState icon={Users} title="No crews have reported yet." />;
  }
  return (
    <div ref={wrap}>
      <DataTable
        caption="Crews (sortable)"
        data={crews}
        columns={columnsFor(crews)}
        getRowId={(c) => c.crew_id}
        selectedId={focus ?? null}
        rowTestId="crew-row"
        edge
        className="overflow-x-auto"
      />
    </div>
  );
}
