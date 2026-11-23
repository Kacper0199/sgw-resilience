import type { Asset, ProposalCard, Region } from "@/lib/api";
import { placeIdsOf } from "./chain";
import type { RiskItem } from "./types";

export const LIFELINE_GROUPS = [
  { key: "substation", label: "Power substations", kinds: ["substation"] },
  { key: "pump_station", label: "Water pump stations", kinds: ["pump_station"] },
  { key: "hospital", label: "Hospitals", kinds: ["critical_customer", "hospital"] },
  { key: "staging", label: "Staging yards and fuel depots", kinds: ["staging_yard", "fuel_depot", "depot"] },
] as const;

const countyName = (name: string): string => name.replace(/ County$/, "");

export const BAND_WORDS: Record<RiskItem["band"], string> = {
  very_low: "Very low",
  low: "Low",
  moderate: "Moderate",
  high: "High",
  very_high: "Very high",
};

const HIGH = new Set(["high", "very_high"]);

export interface LifelineRow {
  key: string;
  label: string;
  total: number;
  highRisk: number;
}

export interface CriticalFacility {
  assetId: string;
  kind: string;
  county: string;
  band: RiskItem["band"] | null;
}

export interface LifelineSummary {
  rows: LifelineRow[];
  critical: CriticalFacility[];
}

export function summariseLifelines(assets: Asset[], regions: Region[], risk: RiskItem[]): LifelineSummary {
  const countyOf = new Map(regions.map((r) => [r.region_id, r]));
  const byCounty = new Map(risk.map((r) => [r.entity_id, r]));
  const riskOf = (a: Asset) => byCounty.get(countyOf.get(a.region_id)?.county_fips ?? "");
  const rows = LIFELINE_GROUPS.map((g) => {
    const members = assets.filter((a) => (g.kinds as readonly string[]).includes(a.kind));
    return {
      key: g.key,
      label: g.label,
      total: members.length,
      highRisk: members.filter((a) => HIGH.has(riskOf(a)?.band ?? "")).length,
    };
  });
  const critical = assets
    .filter((a) => a.critical_facility)
    .map((a) => ({
      assetId: a.asset_id,
      kind: a.kind,
      county: countyName(countyOf.get(a.region_id)?.name ?? a.region_id),
      band: riskOf(a)?.band ?? null,
    }));
  return { rows, critical };
}

/** Decisions that act on the facility itself (as a target, or as the place a resource is sent); only when there
 * are none, the decisions on the pump station that serves it. */
export function facilityDecisions<T extends { card?: Pick<ProposalCard, "target_ids" | "params"> }>(
  assetId: string,
  servingStations: string[],
  open: T[],
): T[] {
  const names = (i: T) => (i.card ? placeIdsOf(i.card) : []);
  const direct = open.filter((i) => names(i).includes(assetId));
  if (direct.length > 0) return direct;
  return open.filter((i) => names(i).some((n) => servingStations.includes(n)));
}
