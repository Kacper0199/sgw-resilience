import { OctagonAlert } from "lucide-react";
import { KeyNumberStrip } from "@/components/sgw";
import { formatEtZ } from "@/lib/time";
import { count } from "./format";
import type { AfterAction } from "./types";

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export function reviewSentence(review: AfterAction): string {
  const { chain } = review;
  if (!chain.ok)
    return `The audit log fails its check from entry ${count(chain.first_bad_seq ?? 0)}. Entries from there on can't be trusted.`;
  const met = review.clocks.filter((c) => c.outcome === "met").length;
  const missed = review.clocks.filter((c) => c.outcome === "missed").length;
  const open = review.clocks.filter((c) => c.outcome === "open").length;
  const flagged = review.break_glass.filter((b) => b.status !== "cosigned_on_time").length;
  const parts = [`${met} met`, `${missed} missed`];
  if (open > 0) parts.push(`${open} still open`);
  const bg = review.break_glass.length;
  return `The audit log passed its check. Of ${review.clocks.length} deadlines, ${parts.join(", ")}. ${
    bg === 0
      ? "No emergency approvals."
      : `${bg} emergency ${plural(bg, "approval", "approvals")}; ${flagged} ${plural(flagged, "needs", "need")} attention.`
  }`;
}

export function Summary({ review }: { review: AfterAction }) {
  const { chain } = review;
  const met = review.clocks.filter((c) => c.outcome === "met").length;
  const missed = review.clocks.filter((c) => c.outcome === "missed").length;
  const open = review.clocks.filter((c) => c.outcome === "open").length;
  const flagged = review.break_glass.filter((b) => b.status !== "cosigned_on_time" || !b.table_agrees).length;
  return (
    <div className="flex flex-col gap-4" id="summary" data-section="summary">
      {!chain.ok && (
        <p role="alert" className="m-0 flex items-center gap-2 text-[15px] font-bold text-crit">
          <OctagonAlert className="size-5 shrink-0" aria-hidden />
          Do not use: the audit log failed its check. Reports from this review carry this warning.
        </p>
      )}
      <p className="m-0 text-[18px] leading-7" data-testid="review-sentence">
        {reviewSentence(review)}
      </p>
      <p className="m-0 text-[13px] text-muted">
        As of <span className="font-semibold text-ink tnum">{formatEtZ(review.as_of)}</span>
      </p>
      <KeyNumberStrip
        className="border-y border-hair px-0 py-4"
        items={[
          {
            label: "Deadlines met",
            info: "clock_outcome",
            value: met,
            line: `of ${review.clocks.length}`,
          },
          {
            label: "Deadlines missed",
            value: missed,
            tone: missed > 0 ? "crit" : undefined,
            line: open > 0 ? `${open} still open` : "None still open",
          },
          {
            label: "Emergency approvals",
            info: "break_glass",
            value: review.break_glass.length,
            tone: flagged > 0 ? "warn" : undefined,
            line: flagged > 0 ? `${flagged} flagged` : "None flagged",
          },
          {
            label: "Audit log",
            info: "ledger",
            value: chain.ok ? "Passed" : "Failed",
            tone: chain.ok ? undefined : "crit",
            line: chain.ok
              ? `Passed through entry ${count(chain.checked_to_seq)}`
              : `Fails at entry ${count(chain.first_bad_seq ?? 0)}`,
          },
        ]}
      />
    </div>
  );
}
