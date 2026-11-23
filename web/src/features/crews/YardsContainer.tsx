import { Warehouse } from "lucide-react";
import { useEffect, useRef } from "react";
import { type DataColumn, DataTable, EmptyState, LoadingState, Section } from "@/components/sgw";
import { LoadFailed } from "@/features/water/LoadFailed";
import { int, PLAN_UI, yardName } from "./format";
import type { CrewPlan, PlanId } from "./types";
import { useCrewList, useCrewPlan } from "./useCrews";

const ORDER: PlanId[] = ["P50", "COA-A", "COA-B", "COA-C"];

interface YardRow {
  id: string;
  byPlan: Partial<Record<PlanId, CrewPlan["yards"][string]>>;
}

const crewsAt = (y: CrewPlan["yards"][string] | undefined) => (y ? y.own_groups + y.mutual_aid_groups : 0);
const shortName = (id: PlanId) => (id === "P50" ? "Standard" : (PLAN_UI[id].name.split(": ")[0] ?? id));

/** Staging yards with the crews each plan option puts there, side by side; `focus` (from `?yard=`) marks one. */
export function YardsContainer({ focus }: { focus?: string | null }) {
  const planQ = useCrewPlan();
  const crewsQ = useCrewList();
  const wrap = useRef<HTMLDivElement>(null);
  const plans = [...(planQ.data?.plans ?? [])].sort(
    (a, b) => ORDER.indexOf(a.plan_id) - ORDER.indexOf(b.plan_id),
  );
  const onHand = new Map<string, number>();
  for (const c of crewsQ.data ?? []) {
    if (c.location_id) onHand.set(c.location_id, (onHand.get(c.location_id) ?? 0) + 1);
  }
  const ids = [...new Set(plans.flatMap((p) => Object.keys(p.yards)))];
  const rows: YardRow[] = ids
    .map((id) => ({ id, byPlan: Object.fromEntries(plans.map((p) => [p.plan_id, p.yards[id]])) }))
    .sort((a, b) => yardName(a.id).name.localeCompare(yardName(b.id).name));
  const ready = rows.length > 0;
  useEffect(() => {
    if (!focus || !ready) return;
    wrap.current
      ?.querySelector<HTMLElement>(`tr[data-row-id="${CSS.escape(focus)}"]`)
      ?.scrollIntoView({ block: "center" });
  }, [focus, ready]);

  const columns: DataColumn<YardRow>[] = [
    {
      id: "yard",
      header: "Yard",
      cell: ({ id }) => <span className="text-[14px] font-medium">{yardName(id).name}</span>,
    },
    ...(rows.some((r) => onHand.has(r.id))
      ? [
          {
            id: "now",
            header: "Crews now",
            align: "end" as const,
            cell: ({ id }: YardRow) => <span className="tnum">{onHand.get(id) ?? "—"}</span>,
          },
        ]
      : []),
    ...plans.map(
      (p): DataColumn<YardRow> => ({
        id: p.plan_id,
        header: shortName(p.plan_id),
        align: "end",
        cell: ({ byPlan }) => <span className="tnum">{int(crewsAt(byPlan[p.plan_id]))}</span>,
      }),
    ),
  ];

  return (
    <Section title="Planned crews per yard" info="staging_yard">
      {planQ.error ? (
        <LoadFailed
          thing="staging yards"
          icon={Warehouse}
          error={planQ.error}
          onRetry={() => void planQ.refetch()}
        />
      ) : planQ.isPending ? (
        <LoadingState label="Loading staging yards…" rows={4} />
      ) : rows.length === 0 ? (
        <EmptyState icon={Warehouse} title="No staging yards in the plan." />
      ) : (
        <div ref={wrap}>
          <DataTable
            caption="Planned crews per yard for each option"
            data={rows}
            columns={columns}
            getRowId={(r) => r.id}
            selectedId={focus ?? null}
            rowTestId="yard-row"
            compact
            className="overflow-x-auto [&_tr>:first-child]:pl-3 [&_tr>:last-child]:pr-0"
          />
        </div>
      )}
    </Section>
  );
}
