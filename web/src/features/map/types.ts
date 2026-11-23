import type { components } from "@/contracts/api.gen";

export type RiskResponse = components["schemas"]["RiskResponse"];
export type RiskItem = components["schemas"]["RiskItem"];

/** `[lead hours from issue, lat, lon, max wind kt]` */
export type TrackFix = [number, number, number, number];
/** `[time UTC, lat, lon, max wind kt]` */
export type AnalysisFix = [string, number, number, number];

export interface AdvisoryIndexItem {
  advisory_label: string;
  issued_utc: string;
  next_advisory_utc: string | null;
}

export interface ConeTable {
  lead_h: number[];
  radius_nmi: number[];
}

/** `GET /api/hazard/advisories/{label}`: the official forecast of one advisory. Not in the K3 contract yet. */
export interface AdvisoryHazard extends AdvisoryIndexItem {
  analysis_track: AnalysisFix[];
  official_track: TrackFix[];
  cone: ConeTable;
  county_peak_gust_ms: Record<string, number>;
}
