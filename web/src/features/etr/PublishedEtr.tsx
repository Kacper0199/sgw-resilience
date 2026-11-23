import { FUNCTION_LABEL } from "@/auth/personas";
import { personaTitle } from "../after-action/format";
import type { Scorecard } from "../after-action/types";
import { when } from "./format";
import { useEtr } from "./useEtr";

const off = (h: number): string =>
  h === 0 ? "Exact" : `${Math.abs(h).toFixed(1)} h ${h > 0 ? "later" : "earlier"} than actual`;

/** The published global ETR at the top of "ETR accuracy": what was published, when, by whom, and once the actual is known, how far off it was. */
export function PublishedEtr({ card }: { card: Scorecard | null }) {
  const etr = useEtr();
  const pub = etr.data?.publication;
  if (pub?.state !== "executed" || !pub.published_at) return null;
  const scored = card?.estimates.find((e) => e.estimate_id === pub.estimate_id);
  const signers = pub.signed_functions.map((f) => FUNCTION_LABEL[f]).join(" and ");
  return (
    <dl
      data-testid="published-etr"
      className="m-0 mb-5 flex flex-wrap gap-x-8 gap-y-3 border-b border-hair pb-4"
    >
      <div className="min-w-0">
        <dt className="text-[12px] font-semibold text-muted">Published ETR, 90% restored</dt>
        <dd className="m-0 text-[20px] leading-7 font-semibold tnum">{when(pub.p50_utc)}</dd>
        <dd className="m-0 text-[12px] text-muted tnum">
          {`Published ${when(pub.published_at)} by ${personaTitle(pub.published_by ?? pub.proposed_by)}`}
          {signers && `, signed by ${signers}`}
        </dd>
      </div>
      {scored?.actual_utc != null && scored.p50_error_h != null && (
        <div className="min-w-0 border-l border-divider pl-4">
          <dt className="text-[12px] font-semibold text-muted">Compared with actual</dt>
          <dd className="m-0 text-[20px] leading-7 font-semibold tnum">{off(scored.p50_error_h)}</dd>
        </div>
      )}
    </dl>
  );
}
