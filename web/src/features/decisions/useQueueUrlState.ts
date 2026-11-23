import { parseAsInteger, parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import type { DomainFilter, QueueFilter, SortKey, TimingFilter } from "./queueModel";

const FILTERS = ["all", "waiting", "decided"] as const satisfies readonly QueueFilter[];
const DOMAINS = ["all", "electric", "water"] as const satisfies readonly DomainFilter[];
const SORTS = ["decide", "severity", "title", "owner"] as const satisfies readonly SortKey[];
export const TABS = ["deadline", "signatures", "sequence", "history"] as const;
const TIMINGS = [
  "all",
  "act_now",
  "decide_now",
  "wait_for_next_advisory",
  "n/a",
] as const satisfies readonly TimingFilter[];
export type InspectorTab = (typeof TABS)[number];

const options = { history: "replace" } as const;

/** Selected decision, filters, sort, page and inspector tab live in the URL so a view can be shared. */
export function useQueueUrlState() {
  const [selectedId, setSelectedId] = useQueryState("d", parseAsString.withOptions(options));
  const [filter, setFilter] = useQueryState(
    "q",
    parseAsStringLiteral(FILTERS).withDefault("all").withOptions(options),
  );
  const [domain, setDomain] = useQueryState(
    "domain",
    parseAsStringLiteral(DOMAINS).withDefault("all").withOptions(options),
  );
  const [owner, setOwner] = useQueryState("owner", parseAsString.withDefault("all").withOptions(options));
  const [timing, setTiming] = useQueryState(
    "timing",
    parseAsStringLiteral(TIMINGS).withDefault("all").withOptions(options),
  );
  const [find, setFind] = useQueryState("find", parseAsString.withDefault("").withOptions(options));
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringLiteral(TABS).withDefault("deadline").withOptions(options),
  );
  const [sort, setSort] = useQueryState(
    "sort",
    parseAsStringLiteral(SORTS).withDefault("decide").withOptions(options),
  );
  const [desc, setDesc] = useQueryState("desc", parseAsString.withOptions(options));
  const [page, setPage] = useQueryState("p", parseAsInteger.withDefault(1).withOptions(options));
  return {
    selectedId,
    setSelectedId,
    filter,
    setFilter,
    domain,
    setDomain,
    owner,
    setOwner,
    timing,
    setTiming,
    find,
    setFind: (v: string) => setFind(v || null),
    tab,
    setTab,
    sort,
    setSort,
    desc: desc === "1",
    setDesc: (v: boolean) => setDesc(v ? "1" : null),
    page,
    setPage,
  };
}
