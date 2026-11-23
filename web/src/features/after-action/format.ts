import { PERSONAS } from "@/auth/personas";
import type { UiSeverity } from "@/contracts/vocab.gen";
import { formatDayET, formatDuration, formatEtZ } from "@/lib/time";
import type { ClockOutcome, CosignStatus, TimelineEntry } from "./types";

export const hours = (h: number): string => `${h.toFixed(1)} h`;
export const share = (s: number): string => `${Math.round(s * 100)}%`;
export const count = (n: number | null): string => (n === null ? "–" : n.toLocaleString("en-US"));

/** Signed error of an estimate: positive means the estimate was later than what happened. */
export const errorText = (h: number): string =>
  h === 0 ? "Exact" : `${hours(Math.abs(h))} ${h > 0 ? "later" : "earlier"} than actual`;

export const marginText = (min: number | null): string => {
  if (min === null) return "";
  if (min === 0) return "At the deadline";
  return `${formatDuration(min)} ${min > 0 ? "before" : "after"} the deadline`;
};

export const KIND_LABEL: Record<string, string> = {
  proposal_created: "Decision proposed",
  proposal_revised: "Decision updated",
  proposal_withdrawn: "Decision withdrawn",
  approval_recorded: "Signature recorded",
  approval_withdrawn: "Signature withdrawn",
  execution_token_issued: "Go-ahead issued",
  execution_token_burned: "Go-ahead used",
  break_glass_used: "Emergency approval used",
  break_glass_cosigned: "Emergency approval co-signed",
  break_glass_cosign_overdue: "Co-sign overdue",
  envelope_approved: "Pre-approved limits set",
  etr_published: "ETR published",
  kill_switch_triggered: "Stop level raised",
  kill_switch_restored: "Stop level lowered",
  degraded_mode_changed: "SGW mode changed",
  security_alert: "Security alert",
  login: "Sign-in",
};

const humanise = (s: string): string => {
  const t = s.replaceAll("_", " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const kindLabel = (kind: string): string => KIND_LABEL[kind] ?? humanise(kind);

const REVISIONS = new Set(["proposal_revised", "proposal_updated"]);
const ADVISORY_REPLANNER = "system:clock-replanner";

/** Labels by sequence number. A signature followed by a revision of the same decision was voided by it (version rule). */
export function entryLabels(
  entries: readonly Pick<TimelineEntry, "seq" | "kind" | "actor_id" | "subject">[],
) {
  const ordered = [...entries].sort((a, b) => a.seq - b.seq);
  const out = new Map<number, string>();
  ordered.forEach((e, i) => {
    let label = kindLabel(e.kind);
    if (e.kind === "approval_recorded") {
      const revision = ordered.slice(i + 1).find((r) => r.subject === e.subject && REVISIONS.has(r.kind));
      if (revision)
        label =
          revision.actor_id === ADVISORY_REPLANNER
            ? "Signature voided — a new advisory moved the deadline"
            : "Signature voided — the decision changed";
    }
    out.set(e.seq, label);
  });
  return out;
}

export const REASON_LABEL: Record<string, string> = {
  approver_unreachable: "Approver unreachable",
  time_critical: "Time critical",
};
export const reasonLabel = (code: string): string => REASON_LABEL[code] ?? humanise(code);

export const personaTitle = (userId: string): string => {
  const p = PERSONAS.find((x) => x.user_id === userId);
  if (p) return p.title;
  if (userId.startsWith("system:rule")) return "SGW rules";
  if (userId.startsWith("system:agent")) return "SGW agent";
  return userId.startsWith("system") ? "System" : userId;
};

/** "proposal:PRP-CREW-AIK-0926A" -> "PRP-CREW-AIK-0926A". */
export const subjectId = (subject: string): string => subject.slice(subject.indexOf(":") + 1);

export const OUTCOME: Record<ClockOutcome, { level: UiSeverity; label: string }> = {
  met: { level: "normal", label: "Met" },
  missed: { level: "critical", label: "Missed" },
  open: { level: "advisory", label: "Still open" },
  unverifiable: { level: "unknown_stale", label: "Can't be checked" },
};

export const COSIGN: Record<CosignStatus, { level: UiSeverity; label: string }> = {
  cosigned_on_time: { level: "normal", label: "Co-signed in time" },
  cosigned_late: { level: "elevated", label: "Co-signed late" },
  overdue_unsigned: { level: "critical", label: "Co-sign overdue" },
  awaiting_cosign: { level: "elevated", label: "Waiting for co-sign" },
  unverifiable: { level: "unknown_stale", label: "Can't be checked" },
};

export const regionLabel = (id: string): string => (id === "GLOBAL" ? "Whole service area" : id);

/** "25 Sep, 22:15 ET (02:15Z)": a clock time with its ET date, since a review spans days. */
export const stamp = (iso: string): string => `${formatDayET(iso)}, ${formatEtZ(iso)}`;

/** Link target for a decision named in a review row. */
