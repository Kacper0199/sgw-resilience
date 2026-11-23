import { useAutoAnimate } from "@formkit/auto-animate/react";
import { CalendarX2, ChevronLeft, ChevronRight, Inbox, Info, Route } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ClockText,
  CountBadge,
  type DataColumn,
  type DataGroup,
  DataTable,
  DataTableToolbar,
  EmptyState,
  ErrorState,
  KeyNumberStrip,
  LoadingState,
  PageHeader,
  SelectField,
  StatusText,
  Tag,
  Tier,
} from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { loadFailureLine } from "@/lib/loadFailure";
import { usePhase } from "@/lib/PhaseProvider";
import {
  formatDayTimeET,
  formatDuration,
  formatET,
  formatETOn,
  formatRelative,
  minutesUntil,
} from "@/lib/time";
import { actionMark, decisionTitle } from "./actionTypes";
import { currentShift, movedNote, useClockShifts } from "./clockShifts";
import {
  type DomainFilter,
  groupOf,
  isMissed,
  type ListRow,
  type MissedRow,
  type OwnerFilter,
  type QueueFilter,
  type QueueRow,
  type SortKey,
  type TimingFilter,
  withMissed,
} from "./queueModel";
import { reorderNotice } from "./reorderNotice";
import { BUCKET_LABEL, BUCKET_ORDER } from "./severity";
import { DOMAIN_LABEL, decisionStatus, timingLabels, timingOf, timingText } from "./ui";
import { PAGE_SIZE, type useQueueTable } from "./useQueueTable";
import { VerdictText } from "./VerdictText";

interface Props {
  table: ReturnType<typeof useQueueTable>;
  rows: QueueRow[];
  missed: MissedRow[];
  now: string;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  filter: QueueFilter;
  onFilter: (f: QueueFilter) => void;
  domain: DomainFilter;
  onDomain: (d: DomainFilter) => void;
  owner: OwnerFilter;
  onOwner: (o: OwnerFilter) => void;
  timing: TimingFilter;
  onTiming: (t: TimingFilter) => void;
  find: string;
  onFind: (v: string) => void;
  sort: SortKey;
  desc: boolean;
  onSort: (key: SortKey) => void;
  page: number;
  onPage: (p: number) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  flashing: ReadonlySet<string>;
}

const Key = ({ children }: { children: React.ReactNode }) => (
  <kbd className="rounded border border-hair-strong px-1 font-mono text-[11px]">{children}</kbd>
);

export function QueueContainer(p: Props) {
  const { advisoriesOver } = usePhase();
  const [bodyRef] = useAutoAnimate<HTMLTableSectionElement>({ duration: 400, easing: "ease-out" });
  const open = p.rows.filter((r) => r.open);
  const mine = p.rows.filter((r) => r.pinned);
  const decided = p.rows.filter((r) => !r.open);
  const twoTeams = open.filter((r) => r.item.summary.functions_required.length >= 2).length;
  const filtered = p.table.getFilteredRowModel().rows;
  const visible = p.table.getRowModel().rows;
  const { shifts } = useClockShifts();
  const orders = useRef<{ prev: string[]; cur: string[] }>({ prev: [], cur: [] });
  const [notice, setNotice] = useState("");
  const ordered = visible.map((r) => r.original);
  const orderKey = visible.map((r) => r.id).join("|");
  useEffect(() => {
    orders.current = { prev: orders.current.cur, cur: orderKey ? orderKey.split("|") : [] };
  }, [orderKey]);
  useEffect(() => {
    const message = reorderNotice(orders.current.prev, ordered, shifts);
    if (message) setNotice(message);
  }, [ordered, shifts]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const first = filtered.length === 0 ? 0 : (p.page - 1) * PAGE_SIZE + 1;
  const owners = [
    ...new Map(p.rows.filter((r) => r.owner.fn).map((r) => [r.owner.fn as string, r.owner.label])),
  ];
  const grouped = p.sort === "decide" && p.filter !== "decided";

  const nowMs = Date.parse(p.now);
  const dated = open.filter((r) => r.decideByMs > 0);
  const ahead = dated.filter((r) => r.decideByMs >= nowMs).sort((a, b) => a.decideByMs - b.decideByMs);
  const next = ahead[0];
  const pastDue = dated.length - ahead.length;
  const nextMin = next ? minutesUntil(next.item.summary.effective_decide_by_utc, p.now) : null;
  const failed = p.error ? loadFailureLine(p.error) : null;
  const strip = [
    { label: "Open decisions", value: failed ? "—" : open.length, line: failed ?? undefined },
    { label: "Need two signatures", value: failed ? "—" : twoTeams },
    { label: "Waiting on you", value: failed ? "—" : mine.length },
    {
      label: "Next deadline",
      value: failed ? "—" : nextMin === null ? (open.length > 0 ? "None due" : "—") : formatDuration(nextMin),
      tone: nextMin !== null && nextMin < 60 ? ("warn" as const) : undefined,
      line: next ? (
        <span title={next.title}>{formatETOn(next.item.summary.effective_decide_by_utc, p.now)}</span>
      ) : (
        (failed ??
        (open.length === 0 ? "Nothing open" : pastDue > 0 ? `${pastDue} past the deadline` : undefined))
      ),
    },
  ];

  const movedText = movedNote(
    filtered
      .map((row) => row.original)
      .filter((r) => r.open)
      .flatMap((r) => {
        const shift = currentShift(
          shifts,
          r.caseId,
          r.item.summary.effective_decide_by_utc,
          r.item.summary.clock_shift,
        );
        return shift ? [{ title: decisionTitle(r.title), shift }] : [];
      }),
  );

  const orderedGroups: DataGroup[] = useMemo(() => {
    const base: DataGroup[] = [
      { id: "mine", label: "Waiting on you" },
      ...BUCKET_ORDER.filter((b) => b !== "closed").map((b) => ({
        id: b,
        label: BUCKET_LABEL[b],
        tone: b === "overdue" ? ("crit" as const) : undefined,
      })),
    ];
    return p.desc ? [...base].reverse() : base;
  }, [p.desc]);

  const closedTab = p.filter === "decided";
  const lastPage = p.page >= pageCount;
  const missed = closedTab && lastPage ? p.missed : [];
  const tableRows: ListRow[] = closedTab ? withMissed(ordered, missed, p.sort === "decide", p.desc) : ordered;
  const shownTotal = filtered.length + (closedTab ? p.missed.length : 0);
  const allColumns: DataColumn<ListRow>[] = [
    {
      id: "severity",
      header: closedTab ? "Outcome" : "Severity",
      sortable: !closedTab,
      className: "w-[104px] max-[819px]:w-[84px]",
      cell: (r) => {
        if (isMissed(r))
          return <StatusText level="critical" label="Missed" className="sgw-card-sev text-[13px]" />;
        const status = decisionStatus(r.item.summary);
        return <StatusText level={status.level} label={status.label} className="sgw-card-sev text-[13px]" />;
      },
    },
    {
      id: "title",
      header: "Decision",
      sortable: true,
      cell: (r) => {
        if (isMissed(r)) {
          return (
            <span className="sgw-card-body flex min-w-0 flex-col gap-1">
              <span className="sgw-card-title flex items-start gap-1.5 text-[14px] leading-[18px] font-medium">
                <CalendarX2 className="mt-[2px] size-3.5 shrink-0 text-muted" aria-hidden />
                <span>{decisionTitle(r.title)}</span>
              </span>
              <span className="sgw-card-meta flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                <Tag domain={r.domain === "water" ? "water" : "power"}>{DOMAIN_LABEL[r.domain]}</Tag>
                No proposal before the deadline
              </span>
            </span>
          );
        }
        const s = r.item.summary;
        const card = r.item.card;
        const mark = actionMark(s.action_type, card?.params);
        return (
          <span className="sgw-card-body flex min-w-0 flex-col gap-1">
            <span className="sgw-card-title flex items-start gap-1.5 text-[14px] leading-[18px] font-medium">
              <mark.Icon className="mt-[2px] size-3.5 shrink-0 text-muted" aria-hidden />
              <span>
                <span className="sr-only">{mark.label}: </span>
                {decisionTitle(s.title)}
              </span>
            </span>
            <span className="sgw-card-meta flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
              {card && (
                <Tag domain={card.case.domain === "water" ? "water" : "power"}>
                  {DOMAIN_LABEL[card.case.domain]}
                </Tag>
              )}
              <Tier tier={s.tier} />
              {s.on_critical_path && (
                <span title="On the critical path" className="inline-flex items-center gap-1">
                  <Route className="size-3" aria-hidden />
                  <span className="sr-only">On the critical path</span>
                </span>
              )}
            </span>
          </span>
        );
      },
    },
    {
      id: "timing",
      header: "Timing",
      className: "sgw-card-hide w-[120px] max-[819px]:hidden @max-[640px]:hidden",
      headerClassName: "max-[819px]:hidden @max-[640px]:hidden",
      cell: (r) =>
        !isMissed(r) && r.item.card && r.open ? (
          <VerdictText verdict={timingOf(r.item.card)} />
        ) : (
          <span className="text-[13px] text-muted">—</span>
        ),
    },
    {
      id: "decide",
      header: "Deadline",
      sortable: true,
      align: "end",
      className: "w-[132px] max-[819px]:w-[96px]",
      cell: (r) =>
        isMissed(r) ? (
          <span className="sgw-card-clock inline-block rounded-sm px-1 py-0.5">
            <span
              className="text-[13px] leading-tight tnum whitespace-nowrap text-muted"
              data-testid="row-outcome"
            >
              {formatDayTimeET(r.decideBy)}
            </span>
          </span>
        ) : (
          <span
            data-testid="row-clock"
            data-flash={p.flashing.has(r.caseId)}
            className={
              p.flashing.has(r.caseId)
                ? "sgw-card-clock inline-block rounded-sm px-1 py-0.5 outline-2 outline-offset-1 outline-blue"
                : "sgw-card-clock inline-block rounded-sm px-1 py-0.5"
            }
          >
            {r.open ? (
              <>
                <span className="max-[819px]:hidden">
                  <ClockText column at={r.item.summary.effective_decide_by_utc} now={p.now} />
                </span>
                <span className="flex flex-col text-end leading-tight tnum whitespace-nowrap min-[820px]:hidden">
                  <span className="text-[13px] font-medium">
                    {formatRelative(r.item.summary.effective_decide_by_utc, p.now)}
                  </span>
                  <span className="font-mono text-[11px] text-muted">
                    {formatET(r.item.summary.effective_decide_by_utc)}
                  </span>
                </span>
              </>
            ) : (
              <span
                className="text-[13px] leading-tight tnum whitespace-nowrap text-muted"
                data-testid="row-outcome"
              >
                {formatDayTimeET(r.item.summary.effective_decide_by_utc)}
              </span>
            )}
          </span>
        ),
    },
  ];

  const anyAdvice = p.rows.some((r) => r.open && timingText(r.verdict, { advisoriesOver }) !== null);
  const showTiming = !closedTab && anyAdvice;
  const columns = showTiming ? allColumns : allColumns.filter((c) => c.id !== "timing");

  const filtersOn = p.domain !== "all" || p.owner !== "all" || p.timing !== "all" || p.find !== "";
  const clearFilters = () => {
    p.onFilter(p.filter === "waiting" ? "all" : p.filter);
    p.onDomain("all");
    p.onOwner("all");
    p.onTiming("all");
    p.onFind("");
  };
  const domainOptions = (["electric", "water"] as const)
    .filter((d) => p.rows.some((r) => r.domain === d))
    .map((d) => ({ value: d, label: DOMAIN_LABEL[d] }));
  const timingOptions = (["act_now", "decide_now", "wait_for_next_advisory", "n/a"] as const)
    .filter((k) => p.rows.some((r) => r.verdict === k))
    .map((k) => ({ value: k, label: k === "n/a" ? "No timing advice" : timingLabels(advisoriesOver)[k] }));

  const empty = (
    <EmptyState
      icon={Inbox}
      title={
        p.filter === "waiting"
          ? "Nothing is waiting on you."
          : p.filter === "decided"
            ? "No decisions are closed yet."
            : "No open decisions match these filters."
      }
      description={filtersOn ? "Clear the filters to see every open decision." : undefined}
      action={
        filtersOn || p.filter === "waiting" ? (
          <Button size="sm" onClick={clearFilters}>
            Clear filters
          </Button>
        ) : undefined
      }
    />
  );

  const body = p.error ? (
    <ErrorState thing="Decisions" title="Couldn't load decisions." error={p.error} onRetry={p.onRetry} />
  ) : p.loading ? (
    <LoadingState label="Loading decisions…" rows={5} />
  ) : (
    <div data-queue className="sgw-cards">
      <DataTable
        caption="Decisions"
        edge
        data={tableRows}
        getRowId={(r) => r.id}
        columns={columns}
        groups={grouped ? orderedGroups : undefined}
        groupOf={grouped ? (r) => (isMissed(r) ? "closed" : groupOf(r)) : undefined}
        selectedId={p.selectedId}
        onSelect={(r) => p.onSelect(r.id)}
        selectable={(r) => !isMissed(r)}
        rowTestId="decision-row"
        sorting={{ id: p.sort, desc: p.desc }}
        onSortingChange={(id) => p.onSort(id as SortKey)}
        bodyRef={bodyRef}
        empty={empty}
      />
    </div>
  );

  return (
    <div className="@container flex h-full min-w-0 flex-col max-[1099px]:h-auto">
      <PageHeader title="Decisions" count={shownTotal} info="queue" />
      <KeyNumberStrip items={strip} />
      <Tabs
        value={p.filter}
        onValueChange={(v) => p.onFilter(v as QueueFilter)}
        className="flex min-h-0 min-w-0 flex-1 flex-col"
      >
        <TabsList aria-label="Show" className="shrink-0 px-8">
          <TabsTrigger value="all">
            All open <CountBadge count={open.length} />
          </TabsTrigger>
          <TabsTrigger value="waiting">
            Waiting on you <CountBadge count={mine.length} />
          </TabsTrigger>
          <TabsTrigger value="decided">
            Closed <CountBadge count={decided.length + p.missed.length} />
          </TabsTrigger>
        </TabsList>
        {(["all", "waiting", "decided"] as const).map((v) => (
          <TabsContent key={v} value={v} className="min-h-0 flex-1 flex-col pt-0 data-[state=active]:flex">
            <DataTableToolbar
              search={p.find}
              onSearch={p.onFind}
              searchLabel="Find a decision"
              placeholder="Find a decision"
              searchClassName="w-auto min-w-[120px] flex-1"
            >
              {domainOptions.length > 1 && (
                <SelectField
                  label="Utility"
                  value={p.domain}
                  onChange={(e) => p.onDomain(e.target.value as DomainFilter)}
                  options={[{ value: "all", label: "All" }, ...domainOptions]}
                />
              )}
              {owners.length > 1 && (
                <SelectField
                  label="Owner"
                  className="w-[132px] [&_select]:w-full [&_select]:min-w-0"
                  value={p.owner}
                  onChange={(e) => p.onOwner(e.target.value)}
                  options={[
                    { value: "all", label: "All" },
                    ...owners.map(([fn, name]) => ({ value: fn, label: name })),
                  ]}
                />
              )}
              {showTiming && timingOptions.length > 1 && (
                <SelectField
                  label="Timing"
                  className="w-[150px] [&_select]:w-full [&_select]:min-w-0"
                  value={p.timing}
                  onChange={(e) => p.onTiming(e.target.value as TimingFilter)}
                  options={[{ value: "all", label: "All" }, ...timingOptions]}
                />
              )}
              {filtersOn && (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="text-[13px] font-semibold text-blue-ink hover:underline"
                >
                  Clear
                </button>
              )}
            </DataTableToolbar>
            <div
              data-scroll-region="decision-list"
              className="min-h-0 flex-1 overflow-y-auto max-[1099px]:overflow-visible"
            >
              {movedText && (
                <p
                  data-testid="moved-note"
                  className="m-0 flex items-center gap-2 border-t border-hair px-8 py-2.5 text-[13px] text-ink-2"
                >
                  <Info className="size-4 shrink-0 text-blue-ink" aria-hidden />
                  {movedText}
                </p>
              )}
              <div role="status" aria-live="polite" className="sr-only" data-testid="reorder-live">
                {notice}
              </div>
              {body}
            </div>
          </TabsContent>
        ))}
      </Tabs>
      <div className="sticky bottom-0 z-10 flex h-10 shrink-0 items-center gap-4 border-t border-hair bg-surface px-8 text-[12px] text-muted">
        <span className="tnum whitespace-nowrap" data-testid="page-range">
          {shownTotal === 0 ? 0 : first || 1}–
          {lastPage ? shownTotal : Math.min(filtered.length, p.page * PAGE_SIZE)} of {shownTotal}
        </span>
        <span className="inline-flex items-center gap-1">
          <IconButton
            small
            label="Previous page"
            icon={<ChevronLeft />}
            disabled={p.page <= 1}
            onClick={() => p.onPage(p.page - 1)}
          />
          <IconButton
            small
            label="Next page"
            icon={<ChevronRight />}
            disabled={p.page >= pageCount}
            onClick={() => p.onPage(p.page + 1)}
          />
        </span>
        <span className="ml-auto inline-flex shrink-0 items-center gap-1 whitespace-nowrap max-[1099px]:hidden">
          <Key>j</Key>
          <Key>k</Key> move
        </span>
      </div>
    </div>
  );
}
