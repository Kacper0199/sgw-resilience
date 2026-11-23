import type { components } from "@/contracts/api.gen";
import type { UiSeverity } from "@/contracts/vocab.gen";
import { plainIds } from "@/lib/names";
import type { Brief, BriefClock, BriefNumber, SitrepDoc, StatusWord } from "./types";

export type LiveBrief = components["schemas"]["ExecutiveBrief"];
export type LiveSitrep = components["schemas"]["SitrepDraft"];
type LiveNumber = components["schemas"]["BriefNumber"];
type LiveClock = components["schemas"]["ProposalSummary"];

export const FOOTER = "Exercise with synthetic data, not for operational use";

/** Who may promote a sitrep draft: the API enforces it (command only); the page only labels the button. */
export const PROMOTE_BY = ["command"] as const;

const SEVERITY_OF_WORD: Record<StatusWord, UiSeverity> = {
  Normal: "normal",
  Watch: "elevated",
  Warning: "severe",
  Emergency: "critical",
  Restoring: "advisory",
};

/** The brief server says "advisory" for a boil-water notice; people know it as a notice. */
const plainNotice = (text: string): string =>
  text
    .replace(/\bunder (?:a boil-water )?advisory\b/gi, "under a boil-water notice")
    .replace(
      /\bboil-water advisor(y|ies)\b/gi,
      (_m, end: string) => `boil-water notice${end === "y" ? "" : "s"}`,
    );

function toNumber(n: LiveNumber, asOf: string): BriefNumber {
  const source = n.provenance.source;
  return {
    key: n.key as BriefNumber["key"],
    label: plainNotice(n.label),
    unit: n.unit,
    actual:
      n.actual === null
        ? null
        : { value: n.actual, as_of: n.provenance.as_of ?? asOf, detail: null, source_id: source },
    forecast:
      n.forecast === null
        ? null
        : { p50: n.forecast, low: null, high: null, basis: n.forecast_basis ?? "", source_id: source },
  };
}

function toClock(c: LiveClock): BriefClock {
  const signed = c.approvals.filter((a) => a.decision === "approve").map((a) => a.function);
  return {
    proposal_id: c.proposal_id,
    decision_case_id: c.decision_case_id ?? null,
    title: c.title,
    tier: c.tier,
    severity: c.severity,
    decide_by_utc: c.decide_by_utc,
    effective_decide_by_utc: c.effective_decide_by_utc,
    waiting_for: c.functions_required.filter((f) => !signed.includes(f)),
    signed,
  };
}

export function toSitrep(d: LiveSitrep): SitrepDoc {
  return {
    run_id: d.run_id,
    as_of_utc: d.as_of_utc ?? d.started_at,
    tier: d.tier ?? "T1",
    path: d.path,
    text: d.text ?? "",
    numbers: Object.entries(d.slots).map(([label, value]) => ({ label, value, source_id: "" })),
    created_at: d.started_at,
    promoted_by: d.promoted_by,
    promoted_at: d.promoted_at,
  };
}

const newest = (a: LiveSitrep, b: LiveSitrep) => Date.parse(b.started_at) - Date.parse(a.started_at);

export function toBrief(b: LiveBrief, sitreps: LiveSitrep[]): Brief {
  const sorted = [...sitreps].sort(newest);
  const current = sorted.find((s) => s.status === "promoted");
  const draft = sorted.find((s) => s.status === "draft");
  const word = b.status_word;
  return {
    as_of: b.as_of,
    status: { word, severity: SEVERITY_OF_WORD[word], reason: plainIds(b.status_basis) },
    last_advisory: b.last_advisory
      ? {
          label: b.last_advisory.label,
          issued_utc: b.last_advisory.issued_utc,
          next_utc: b.last_advisory.next_advisory_utc,
        }
      : null,
    numbers: b.numbers.map((n) => toNumber(n, b.as_of)),
    open_t3: b.open_t3.map(toClock),
    functions: b.functions.map((f) => ({
      function: f.function,
      sentence: plainIds(plainNotice(f.sentence)),
    })),
    caveat: b.caveat,
    sitrep: {
      current: current ? toSitrep(current) : null,
      draft: draft ? toSitrep(draft) : null,
      promote_by: [...PROMOTE_BY],
    },
    footer: FOOTER,
  };
}
