import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { useNavigate } from "react-router";
import { useMe } from "@/auth/useSession";
import { SplitPane } from "@/components/sgw";
import { decisionPageHref } from "@/lib/links";
import { overlayOpen } from "@/lib/overlay";
import { useScenarioNow } from "@/sse/useScenarioNow";
import { useClockShifts } from "./clockShifts";
import { Inspector } from "./Inspector";
import { QueueContainer } from "./QueueContainer";
import { useAssetIndex } from "./queries";
import { toMissedRows, toRows } from "./queueModel";
import { useListed, useMissedCases, useQueue } from "./useQueue";
import { PAGE_SIZE, useQueueTable } from "./useQueueTable";
import { useQueueUrlState } from "./useQueueUrlState";

const NARROW = "(max-width: 819px)";
const subscribeNarrow = (cb: () => void) => {
  const mq = window.matchMedia(NARROW);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};
/** On a phone (below 820 px) there is no pane: a row opens the full page. Between 820 and 1099 px the pane sits under the list. */
const useNarrow = () => useSyncExternalStore(subscribeNarrow, () => window.matchMedia(NARROW).matches);

/** Arrow keys scroll the page and the inspector; they only move the selection when focus is in the queue or on nothing. */
const inQueue = (e: KeyboardEvent): boolean => {
  const target = e.target as Element | null;
  return !target || target === document.body || Boolean(target.closest?.("[data-queue]"));
};

export default function DecisionsPage() {
  const me = useMe().data;
  const navigate = useNavigate();
  const now = useScenarioNow() ?? new Date().toISOString();
  const queue = useQueue();
  const assets = useAssetIndex();
  const url = useQueueUrlState();
  const { selectedId } = url;
  const { flashing } = useClockShifts();
  const heading = useRef<HTMLHeadingElement>(null);
  const narrow = useNarrow();

  const rows = useMemo(() => toRows(queue.items, me, now, assets), [queue.items, me, now, assets]);
  const missedCases = useMissedCases(now).data;
  const missed = useMemo(
    () => toMissedRows(missedCases ?? [], url.domain, url.owner, url.find),
    [missedCases, url.domain, url.owner, url.find],
  );
  const table = useQueueTable({ rows, ...url });
  const filteredCount = table.getFilteredRowModel().rows.length;
  const order = table.getRowModel().rows.map((r) => r.id);

  useEffect(() => {
    const last = Math.max(1, Math.ceil(filteredCount / PAGE_SIZE));
    if (url.page > last) void url.setPage(last);
  }, [filteredCount, url.page, url.setPage]);

  const filterKey = `${url.filter}|${url.domain}|${url.owner}|${url.timing}|${url.find}`;
  const lastFilterKey = useRef(filterKey);
  useEffect(() => {
    if (lastFilterKey.current === filterKey) return;
    lastFilterKey.current = filterKey;
    const inView = table.getFilteredRowModel().rows.some((r) => r.id === selectedId);
    if (!inView) void url.setSelectedId(order[0] ?? null);
  });

  const listed = useListed(selectedId);
  useEffect(() => {
    if (listed.gone) void url.setSelectedId(order[0] ?? null);
  });

  const autoSelected = useRef(false);
  useEffect(() => {
    if (autoSelected.current || selectedId || !order[0]) return;
    autoSelected.current = true;
    void url.setSelectedId(order[0]);
  });
  const close = () => {
    autoSelected.current = true;
    void url.setSelectedId(null);
  };
  const select = (id: string) => void url.setSelectedId(id);

  const step = (delta: 1 | -1) => {
    const i = selectedId ? order.indexOf(selectedId) : -1;
    const next = order[Math.min(order.length - 1, Math.max(0, i + delta))];
    if (next) select(next);
  };
  const listKeys = (e: KeyboardEvent) => !overlayOpen(e);
  const arrowKeys = (e: KeyboardEvent) => !overlayOpen(e) && inQueue(e);
  useHotkeys("j", () => step(1), { enabled: listKeys });
  useHotkeys("k", () => step(-1), { enabled: listKeys });
  useHotkeys("down", () => step(1), { enabled: arrowKeys, preventDefault: true });
  useHotkeys("up", () => step(-1), { enabled: arrowKeys, preventDefault: true });
  useHotkeys("enter", () => heading.current?.focus(), {
    enabled: (e) => Boolean(selectedId) && !overlayOpen(e),
  });
  useHotkeys("o", () => selectedId && navigate(decisionPageHref(selectedId)), {
    enabled: (e) => Boolean(selectedId) && !overlayOpen(e),
  });
  // Radix marks an Escape it used to close a popover or dialog as handled; only an unhandled Escape closes the inspector.
  useHotkeys("escape", close, {
    enabled: (e) => Boolean(selectedId) && !e.defaultPrevented && !overlayOpen(e),
  });

  const onSort = (key: typeof url.sort) => {
    if (key === url.sort) void url.setDesc(!url.desc);
    else {
      void url.setSort(key);
      void url.setDesc(false);
    }
    void url.setPage(1);
  };

  return (
    <SplitPane
      id="decisions"
      mainMinSize={420}
      end={
        narrow
          ? null
          : {
              label: "Resize decision details",
              scrollRegion: "decision-detail",
              defaultSize: "38%",
              minSize: 340,
              maxSize: "62%",
              content: (
                <aside aria-label="Decision details" className="h-full min-w-0">
                  <Inspector
                    ref={heading}
                    id={listed.id}
                    now={now}
                    tab={url.tab}
                    onTab={(t) => void url.setTab(t)}
                    onClose={close}
                    onSelectCase={select}
                    onSelectProposal={select}
                  />
                </aside>
              ),
            }
      }
    >
      <div className="h-full min-w-0 max-[1099px]:h-auto" data-testid="queue-pane">
        <QueueContainer
          table={table}
          rows={rows}
          missed={missed}
          now={now}
          loading={queue.isPending}
          error={queue.error}
          onRetry={() => void queue.refetch()}
          filter={url.filter}
          onFilter={(f) => {
            void url.setFilter(f);
            void url.setPage(1);
          }}
          domain={url.domain}
          onDomain={(d) => {
            void url.setDomain(d);
            void url.setPage(1);
          }}
          owner={url.owner}
          onOwner={(o) => {
            void url.setOwner(o);
            void url.setPage(1);
          }}
          timing={url.timing}
          onTiming={(t) => {
            void url.setTiming(t);
            void url.setPage(1);
          }}
          find={url.find}
          onFind={(v) => {
            void url.setFind(v);
            void url.setPage(1);
          }}
          sort={url.sort}
          desc={url.desc}
          onSort={onSort}
          page={url.page}
          onPage={(p) => void url.setPage(p)}
          selectedId={selectedId}
          onSelect={(id) => (narrow ? navigate(decisionPageHref(id)) : select(id))}
          flashing={flashing}
        />
      </div>
    </SplitPane>
  );
}
