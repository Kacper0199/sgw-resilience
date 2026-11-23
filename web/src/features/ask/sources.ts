import type { Domain } from "@/components/sgw";
import { TOOL_LABEL } from "../agent-panel/labels";
import { toolArg } from "../agent-panel/ToolChip";
import type {
  ParsedAnswer,
  Reference,
  RunView,
  SourceCite,
  ToolCall,
  ToolStatus,
} from "../agent-panel/types";

export interface PlatformSource {
  key: string;
  tool: string;
  label: string;
  /** The plain name of what was read when the row has no page of its own ("Hold Cedarfall zone pressure…"). */
  title: string | null;
  /** The decision case id for a decision case; the main argument otherwise. */
  id: string | null;
  decisionCaseId: string | null;
  domain: Domain | null;
  status: ToolStatus;
  quote: string | null;
}

export interface SourceSet {
  docs: SourceCite[];
  platform: PlatformSource[];
}

/** Code-answer rows that count or summarise ("Closed so far: …", "10 more open decisions…"): not a source of their own. */
const COUNT_ROWS = new Set(["closed", "more", "none"]);

const DOMAIN_OF: Record<string, Domain> = { get_water_status: "water", get_forecast: "power" };

const RISK_LEVEL: Record<string, string> = { county: "by county", asset: "at named assets", h3: "by area" };

/** A decision case id in words when no title is known: "DC-D3-PS17-PRESSURE" reads "PS-17 pressure decision". */
export function caseWords(caseId: string): string {
  const parts = caseId
    .split("-")
    .slice(2)
    .map((p) => (/^PS\d+$/.test(p) ? `PS-${p.slice(2)}` : p.toLowerCase()));
  const words = parts.filter((p) => !["aik", "hsp", "rch"].includes(p)).join(" ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)} decision`;
}

/** The entity a lookup was about, when it names one; levels, targets and searches are not entities. */
function entityOf(t: ToolCall): string | null {
  const a = t.args;
  if (t.tool === "get_decision_case") return String(a.decision_case_id ?? "") || null;
  if (typeof a.entity_id === "string") return a.entity_id;
  const ids = Array.isArray(a.entity_ids) ? a.entity_ids : Array.isArray(a.feeder_ids) ? a.feeder_ids : [];
  if (ids.length === 1) return String(ids[0]);
  if (t.tool === "get_risk" || t.tool === "get_water_status" || t.tool === "get_outages") return null;
  const arg = toolArg(a);
  return arg && !/^\d+$/.test(arg) ? arg : null;
}

function labelOf(t: ToolCall): string {
  if (t.tool === "get_risk") {
    const ids = Array.isArray(t.args.entity_ids) ? t.args.entity_ids : [];
    return ids.length === 1 ? "Outage risk" : `Outage risk ${RISK_LEVEL[String(t.args.level)] ?? ""}`.trim();
  }
  return TOOL_LABEL[t.tool] ?? t.tool;
}

/**
 * What an answer was built from, for the Sources panel and its count: cited documents and platform lookups. A lookup
 * made twice (two analysts read the same decision or the same queue) is one source; a decision carries the plain title the answer's
 * references give it.
 */
export function sourcesOf(
  parsed: ParsedAnswer | null,
  run: RunView | null,
  references: readonly Reference[] = [],
): SourceSet {
  if (!parsed) return { docs: [], platform: [] };
  const docs = parsed.citations;
  const tools = (run?.tools ?? []).filter((t) => t.tool !== "search_procedures" && !t.empty);
  if (tools.length > 0) {
    const seen = new Map<string, PlatformSource>();
    for (const t of tools) {
      const isCase = t.tool === "get_decision_case";
      const arg = entityOf(t);
      const label = labelOf(t);
      const key = `${t.tool}|${arg ?? ""}|${label}`;
      const earlier = seen.get(key);
      if (earlier) {
        if (earlier.status !== "ok" && t.status === "ok") earlier.status = "ok";
        continue;
      }
      const row = arg ? parsed.platform.find((p) => p.id === arg) : undefined;
      const named = arg ? references.find((r) => r.id === arg) : undefined;
      seen.set(key, {
        key: `tool-${t.call}`,
        tool: t.tool,
        label,
        title: isCase && arg ? (named?.label ?? caseWords(arg)) : (named?.label ?? null),
        id: arg,
        decisionCaseId: isCase ? arg : null,
        domain: DOMAIN_OF[t.tool] ?? null,
        status: t.status,
        quote: row?.text ?? null,
      });
    }
    return { docs, platform: [...seen.values()] };
  }
  return {
    docs,
    platform: parsed.platform
      .filter((p) => !COUNT_ROWS.has(p.id))
      .map((p) => {
        const isCase = p.id.startsWith("DC-");
        const named = references.find((r) => r.id === p.id)?.label;
        return {
          key: `row-${p.id}`,
          tool: "platform",
          label: "Platform data",
          title: named ?? (isCase ? caseWords(p.id) : null),
          id: p.id,
          decisionCaseId: isCase ? p.id : null,
          domain: null,
          status: "ok" as const,
          quote: p.text,
        };
      }),
  };
}

export const sourceCount = (s: SourceSet): number => s.docs.length + s.platform.length;
