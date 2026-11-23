import { modelName } from "@/lib/plain";
import { formatDayET, formatET } from "@/lib/time";
import type { FeedHealthItem } from "./types";

export { modelName };

const ACRONYMS: Record<string, string> = {
  nws: "NWS",
  nhc: "NHC",
  asos: "ASOS",
  eam: "EAM",
  scada: "SCADA",
  usgs: "USGS",
  eaglei: "EAGLE-I",
  sop: "SOP",
  etr: "ETR",
  llm: "LLM",
  saa: "SAA",
  rag: "RAG",
  ai: "AI",
  dq: "DQ",
  psi: "psi",
  obs: "observations",
};

export const humanize = (id: string): string => {
  const words = id
    .split(/[_.\-:\s]+/)
    .filter(Boolean)
    .map((w, i) => ACRONYMS[w.toLowerCase()] ?? (i === 0 ? w[0]?.toUpperCase() + w.slice(1) : w));
  return words.length ? words.join(" ") : id;
};

export function ageText(seconds: number | null): string {
  if (seconds === null) return "No data yet";
  if (seconds < 90) return `${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.round(seconds / 3600);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(seconds / 86_400)} d`;
}

/** "27 Sep, 23:29 ET": local time first, as everywhere else. */
export const dayTime = (iso: string): string => `${formatDayET(iso)}, ${formatET(iso)}`;

export const PLATFORM_CLOCK = "Real time when it ran, not a time in the scenario.";

/** A time on the platform's own clock (runs, tests), with its year so it never reads as a scenario time. */
export const platformTime = (iso: string): string =>
  `${formatDayET(iso)} ${new Date(iso).getUTCFullYear()}, ${formatET(iso)}`;

export function tookText(startIso: string, endIso: string | null): string {
  if (!endIso) return "Running";
  const s = Math.max(0, Math.round((Date.parse(endIso) - Date.parse(startIso)) / 1000));
  return s < 90 ? `${s} s` : `${Math.round(s / 60)} min`;
}

export function durationMs(ms: number | null): string {
  if (ms === null) return "Running";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 90) return `${s.toFixed(1)} s`;
  return `${Math.round(s / 60)} min`;
}

export function tokens(n: number): string {
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
}

export const usd = (value: number): string => (value > 0 && value < 0.01 ? "<$0.01" : `$${value.toFixed(2)}`);

export const usdMicros = (micros: number): string => usd(micros / 1_000_000);

export const shortHash = (hash: string): string => hash.slice(0, 8);

export const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

export const list = (items: string[]): string =>
  items.length <= 2 ? items.join(" and ") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;

export const firstSentence = (text: string): string => {
  const flat = text.replace(/\s+/g, " ").trim();
  const end = flat.search(/\.(\s|$)/);
  return end === -1 ? flat : flat.slice(0, end + 1);
};

export const FEED_MODE_LABEL = { live: "Live", replay: "Replay", synthetic: "Synthetic" } as const;

export const sentence = (text: string): string => (text ? text[0]?.toUpperCase() + text.slice(1) : text);

/** A feed's name in plain words: the server's `display_name` (one registry), else the id spelled out. */
export const feedName = (f: { source_id: string; display_name?: string | null }): string =>
  f.display_name || humanize(f.source_id);

const GRAPH_NAME: Record<string, string> = {
  copilot: "Ask AI",
  sitrep: "Situation report",
};

/** What a run is called on screen: the product name of its graph ("copilot" is Ask AI). */
export const graphName = (graph: string): string => GRAPH_NAME[graph] ?? humanize(graph);

/** The value a feed's freshness is judged by: the delay of its newest data for feeds that report on change, else its age. */
export function measured(feed: FeedHealthItem): { seconds: number | null; text: string } {
  if (feed.measured_by === "delay") {
    const lag = feed.ingest_lag_s;
    return { seconds: lag, text: lag === null ? ageText(null) : `${ageText(lag)} delay` };
  }
  return { seconds: feed.product_age_s, text: ageText(feed.product_age_s) };
}

const ASSET_PLAIN: Record<string, { name: string; text: string }> = {
  "ingest.feeds": { name: "Incoming data", text: "Pulls new readings from every data source." },
  "ledger.reconcile": { name: "Record check", text: "Every event received is in the log exactly once." },
  "ledger.relay": { name: "Log update", text: "Moves new events into the audit log without gaps." },
  observations: { name: "Readings check", text: "Readings are numbers with units and no conflicts." },
  "opendata.helene": {
    name: "Helene public data",
    text: "River gauges, wind, warnings and disaster declarations.",
  },
  "surge.outages": { name: "Outage surges", text: "Sudden rises in customers out, county by county." },
  "risk.snapshot": { name: "Risk forecast", text: "County outage and asset risk for the latest advisory." },
};

/** A pipeline step in plain words; an unknown step falls back to its spelled-out id and first sentence. */
export const assetLabel = (name: string, description = ""): { name: string; text: string } =>
  ASSET_PLAIN[name] ?? { name: humanize(name), text: firstSentence(description) };

export type FeedStatus = "on_time" | "late" | "no_data" | "quiet";

/** The one status a feed shows: nothing delivered yet is "no data" (or "quiet" for a feed that reports only on change), never "on time". */
export const feedStatus = (feed: FeedHealthItem): FeedStatus =>
  feed.status ??
  (feed.product_age_s === null && feed.ingest_lag_s === null ? "no_data" : feed.stale ? "late" : "on_time");
