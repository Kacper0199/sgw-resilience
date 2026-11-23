import { Gauge, TriangleAlert } from "lucide-react";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { FUNCTION_LABEL, PERSONAS } from "@/auth/personas";
import {
  type DataColumn,
  type DataGroup,
  DataTable,
  EmptyState,
  InfoTip,
  LoadingState,
  PageHeader,
  SegmentedControl,
  SplitPane,
  StatusText,
  Tag,
} from "@/components/sgw";
import type { UiSeverity } from "@/contracts/vocab.gen";
import { cn } from "@/lib/cn";
import { plainIds } from "@/lib/names";
import { formatDayET, formatET } from "@/lib/time";
import { FOCUS_ROW_CLASS, useFocusRow } from "@/lib/useFocusRow";
import { useScenarioNow } from "@/sse/useScenarioNow";
import { ViewDecision } from "../agent-panel/decisionLink";
import { OPEN_STATES } from "../decisions/severity";
import { useQueue } from "../decisions/useQueue";
import { HeatView } from "./HeatView";
import { assetIdsIn, calendarDay, dueText, GROUPS, grouped, isOverdue, reviewTime } from "./model";
import { ReadinessTabs, useReadinessView } from "./ReadinessTabs";
import { RecordResult } from "./RecordResult";
import type { ReadinessItem } from "./types";
import { useReadiness } from "./useReadiness";
import { WildfireView } from "./WildfireView";

const DOMAINS = ["all", "electric", "water"] as const;
const DOMAIN_OPTIONS = [
  { value: "all", label: "All" },
  { value: "electric", label: "Power" },
  { value: "water", label: "Water" },
] as const;

const absolute = (iso: string) => `${formatDayET(iso)}, ${formatET(iso)}`;

function statusOf(item: ReadinessItem, now: string): { level: UiSeverity; label: string } {
  if (item.status === "ready") return { level: "normal", label: "Ready" };
  if (item.status === "waived") return { level: "normal", label: "Waived" };
  if (item.status === "unknown") return { level: "unknown_stale", label: "No record" };
  return isOverdue(item, now)
    ? { level: "severe", label: "Overdue" }
    : { level: "elevated", label: "Not ready" };
}

function missingText(item: ReadinessItem, now: string, review: string | null): string {
  if (item.status === "ready") return "Nothing is missing. This check is ready.";
  if (item.status === "waived") return "Nothing is required. This check was waived.";
  if (item.status === "unknown") return "No result has been recorded for this check yet.";
  const due = item.due_utc;
  if (review)
    return isOverdue(item, now)
      ? `This check was not ready and its date (${due ? calendarDay(due) : "none"}) had passed at the review.`
      : `This check was not ready at the review${due ? `; it is due ${calendarDay(due)}` : ""}.`;
  if (isOverdue(item, now))
    return `This check is not ready and its date has passed: ${due ? dueText(due, now) : "overdue"}.`;
  return `This check is not ready yet${due ? `, and it is due ${dueText(due, now)}` : ""}.`;
}

function columns(now: string, review: string | null): DataColumn<ReadinessItem>[] {
  return [
    {
      id: "status",
      header: "Status",
      cell: (i) => <StatusText {...statusOf(i, now)} />,
    },
    {
      id: "check",
      header: "Check",
      cell: (i) => (
        <div>
          <div className="text-[14px] leading-snug font-medium">{plainIds(i.title)}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
            <Tag domain={i.domain === "electric" ? "power" : "water"}>
              {i.domain === "electric" ? "Power" : "Water"}
            </Tag>
            <span>{FUNCTION_LABEL[i.owner_function]}</span>
          </div>
        </div>
      ),
    },
    {
      id: "due",
      header: "Due",
      align: "end",
      cell: (i) =>
        i.due_utc ? (
          <span className="flex flex-col text-end leading-tight tnum whitespace-nowrap">
            <span
              className={cn(
                "text-[13px] font-semibold",
                isOverdue(i, now) ? "text-crit" : i.status === "ready" ? "text-muted" : "text-ink",
              )}
            >
              {review ? calendarDay(i.due_utc) : dueText(i.due_utc, now)}
            </span>
            {!review && <span className="text-[11px] text-muted">{absolute(i.due_utc)}</span>}
          </span>
        ) : (
          <span className="text-[13px] text-muted">No date</span>
        ),
    },
  ];
}

function Fact({ label, children, sub }: { label: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className="m-0 text-[14px] font-semibold">{children}</dd>
      {sub && <dd className="m-0 text-[12px] text-muted">{sub}</dd>}
    </div>
  );
}

/** Open decisions that act on the same equipment this check is about, each a link into Decisions. */
function UsedBy({ item }: { item: ReadinessItem }) {
  const { items } = useQueue();
  const ids = assetIdsIn(item.title);
  const users = items.filter(
    (i) => OPEN_STATES.has(i.summary.state) && i.card?.target_ids.some((t) => ids.includes(t)),
  );
  if (users.length === 0)
    return <p className="m-0 mt-3 text-[14px] text-muted">No open decision depends on this check yet.</p>;
  return (
    <ul className="m-0 mt-2 list-none p-0" data-testid="used-by">
      {users.map((u) => (
        <li
          key={u.summary.proposal_id}
          className="flex flex-col gap-0.5 border-b border-hair py-2.5 last:border-b-0"
        >
          <span className="text-[14px] leading-[18px] font-medium">{u.summary.title}</span>
          <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
            <ViewDecision id={u.summary.proposal_id} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function Recorded({ result }: { result: NonNullable<ReadinessItem["result"]> }) {
  const who = PERSONAS.find((p) => p.user_id === result.recorded_by)?.title ?? result.recorded_by;
  return (
    <p className="m-0 mt-3 text-[14px] leading-[22px]" data-testid="readiness-result">
      <span className="text-muted">{who}: </span>
      {result.note}
      {result.evidence_url && (
        <>
          {" "}
          <a
            href={result.evidence_url}
            target="_blank"
            rel="noreferrer noopener"
            className="font-semibold text-blue-ink hover:underline"
          >
            Evidence
          </a>
        </>
      )}
    </p>
  );
}

function Detail({ item, now, review }: { item: ReadinessItem; now: string; review: string | null }) {
  const status = statusOf(item, now);
  return (
    <div data-testid="readiness-detail" className="px-6 py-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <StatusText {...status} />
        <Tag domain={item.domain === "electric" ? "power" : "water"}>
          {item.domain === "electric" ? "Power" : "Water"}
        </Tag>
      </div>
      <h2 className="m-0 mt-2 text-[20px] leading-[26px] font-semibold">{plainIds(item.title)}</h2>
      <dl className="m-0 mt-5 grid grid-cols-2 gap-x-6 gap-y-4">
        <Fact label="Due" sub={item.due_utc && !review ? absolute(item.due_utc) : undefined}>
          {item.due_utc ? (review ? calendarDay(item.due_utc) : dueText(item.due_utc, now)) : "No date"}
        </Fact>
        <Fact label="Owner">{FUNCTION_LABEL[item.owner_function]}</Fact>
        <Fact label="Utility">{item.domain === "electric" ? "Power" : "Water"}</Fact>
        <Fact label="Status">{status.label}</Fact>
      </dl>
      <h3 className="m-0 mt-6 border-b border-hair pb-2 text-[15px] leading-5 font-bold">What is missing</h3>
      <p className="m-0 mt-3 text-[14px] leading-[22px]">{missingText(item, now, review)}</p>
      {item.result && <Recorded result={item.result} />}
      <RecordResult item={item} review={review} />
      <h3 className="m-0 mt-6 border-b border-hair pb-2 text-[15px] leading-5 font-bold">Used by</h3>
      <UsedBy item={item} />
    </div>
  );
}

export default function ReadinessPage() {
  const clock = useScenarioNow();
  const [view] = useReadinessView();
  if (view === "heat") return <HeatView />;
  if (view === "wildfire") return <WildfireView />;
  return <ReadinessView now={clock ?? new Date().toISOString()} />;
}

export function ReadinessView({ now: clock }: { now: string }) {
  const readiness = useReadiness();
  const review = reviewTime(readiness.data ?? []);
  const now = review ?? clock;
  const [domain, setDomain] = useQueryState("domain", parseAsStringLiteral(DOMAINS).withDefault("all"));
  const [itemParam, setItemParam] = useQueryState("item", parseAsString);
  const [checkParam] = useQueryState("check", parseAsString);
  const all = readiness.data ?? [];
  const items = domain === "all" ? all : all.filter((i) => i.domain === domain);
  const g = grouped(items);
  const ordered = [...g.gap, ...g.unknown, ...g.ready, ...g.waived];
  const focusId = itemParam ?? checkParam;
  const selected = ordered.find((i) => i.item_id === focusId) ?? ordered[0] ?? null;
  const focusIsReady = [...g.ready, ...g.waived].some((i) => i.item_id === checkParam);
  useFocusRow(
    checkParam,
    ordered.some((i) => i.item_id === checkParam),
  );
  const overdue = items.filter((i) => isOverdue(i, now));
  const next = [...g.gap, ...g.unknown].find((i) => i.due_utc && !isOverdue(i, now));
  const groups: DataGroup[] = GROUPS.map((grp) => ({
    id: grp.status,
    label: grp.title,
    tone: grp.status === "gap" ? "warn" : "neutral",
    ...((grp.status === "ready" || grp.status === "waived") && !focusIsReady
      ? { folded: true, note: "folded because nothing needs attention" }
      : {}),
  }));

  return (
    <SplitPane
      id="readiness"
      mainScrollRegion="readiness-list"
      stackBelow={1280}
      mainMinSize={440}
      end={
        selected
          ? {
              label: "Resize check details",
              scrollRegion: "readiness-detail",
              defaultSize: "36%",
              minSize: 340,
              maxSize: "60%",
              content: (
                <aside aria-label="Check details">
                  <Detail item={selected} now={now} review={review} />
                </aside>
              ),
            }
          : null
      }
    >
      <div className="min-w-0 pb-8">
        <PageHeader
          title="Readiness"
          info="readiness"
          actions={
            all.length > 0 && (
              <SegmentedControl
                label="Utility"
                value={domain}
                onValueChange={(v) => void setDomain(v)}
                options={DOMAIN_OPTIONS}
              />
            )
          }
        />
        <ReadinessTabs />
        {readiness.isPending ? (
          <LoadingState rows={5} label="Loading readiness…" className="px-8" />
        ) : readiness.error ? (
          <EmptyState role="alert" icon={TriangleAlert} title="Couldn't load readiness." />
        ) : all.length === 0 ? (
          <EmptyState icon={Gauge} title="No readiness checks yet." />
        ) : items.length === 0 ? (
          <EmptyState icon={Gauge} title="No checks for this utility." />
        ) : (
          <>
            <p
              data-testid="readiness-summary"
              className="m-0 flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b border-hair px-8 pt-1 pb-3 text-[15px]"
            >
              {review && (
                <span className="text-muted" data-testid="readiness-review">
                  Pre-season review, {calendarDay(review)}
                </span>
              )}
              <span>
                <b className="font-semibold tnum">{g.ready.length}</b> of {items.length} ready
                <InfoTip term="readiness_status" />
              </span>
              {overdue.length > 0 && (
                <span className="text-warn">
                  <b className="font-semibold tnum">{overdue.length}</b> overdue
                </span>
              )}
              {next?.due_utc && (
                <span className="text-muted">
                  Next due{" "}
                  {review ? calendarDay(next.due_utc) : dueText(next.due_utc, now).replace(/^in /, "")}
                </span>
              )}
            </p>
            <DataTable
              caption="Readiness checks"
              data={ordered}
              getRowId={(i) => i.item_id}
              rowTestId="readiness-row"
              groups={groups}
              groupOf={(i) => i.status}
              selectedId={selected?.item_id ?? null}
              onSelect={(i) => void setItemParam(i.item_id)}
              columns={columns(now, review)}
              edge
              className={FOCUS_ROW_CLASS}
            />
          </>
        )}
      </div>
    </SplitPane>
  );
}
