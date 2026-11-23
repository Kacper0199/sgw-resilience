import { Siren } from "lucide-react";
import { EmptyState, InfoTip, StatusText } from "@/components/sgw";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { formatDuration } from "@/lib/time";
import { COSIGN, personaTitle, reasonLabel } from "./format";
import { Stamp, ViewDecision } from "./parts";
import type { BreakGlassUse } from "./types";

function lateBy(use: BreakGlassUse): string | null {
  if (!use.cosigned_at) return null;
  const min = Math.round((Date.parse(use.cosigned_at) - Date.parse(use.cosign_due)) / 60_000);
  return min > 0 ? `${formatDuration(min)} after the window closed` : null;
}

function isFlagged(use: BreakGlassUse): boolean {
  return use.status !== "cosigned_on_time" || !use.table_agrees;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] font-semibold text-muted">{label}</dt>
      <dd className="m-0 text-[14px]">{children}</dd>
    </div>
  );
}

export function BreakGlassTab({ uses }: { uses: BreakGlassUse[] }) {
  if (uses.length === 0) return <EmptyState icon={Siren} title="No emergency approvals in this event." />;
  return (
    <div className="flex flex-col gap-1">
      <p className="m-0 flex items-center gap-1 text-[13px] text-muted">
        Every emergency approval is reviewed after the event. A second team must co-sign within 24 hours.
        <InfoTip term="cosign" />
      </p>
      <ul className="m-0 list-none p-0">
        {uses.map((u) => {
          const st = COSIGN[u.status];
          const late = lateBy(u);
          return (
            <li
              key={u.break_glass_id}
              data-testid="break-glass-row"
              data-flagged={isFlagged(u)}
              className="border-b border-hair py-4 last:border-b-0"
            >
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                <div className="min-w-0">
                  <p className="m-0 text-[14px] leading-[18px] font-medium">
                    {u.title ? decisionTitle(u.title) : u.proposal_id}
                  </p>
                  <p className="m-0 mt-0.5">
                    <ViewDecision id={u.proposal_id} />
                  </p>
                </div>
                <StatusText level={st.level} label={st.label} />
              </div>
              <dl className="m-0 mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">
                <Fact label="Used by">{personaTitle(u.ic_id)}</Fact>
                <Fact label="Used at">
                  <Stamp iso={u.used_at} utc={false} />
                </Fact>
                <Fact label="Co-sign due">
                  <Stamp iso={u.cosign_due} utc={false} />
                </Fact>
                <Fact label="Co-signed by">
                  {u.cosigned_by && u.cosigned_at ? (
                    <>
                      {personaTitle(u.cosigned_by)}
                      <span className="block text-[12px] text-muted tnum">
                        <Stamp iso={u.cosigned_at} utc={false} />
                        {late && <span className="block">{late}</span>}
                      </span>
                    </>
                  ) : (
                    <span className="text-muted">Not yet</span>
                  )}
                </Fact>
                <div className="min-w-0 sm:col-span-2 xl:col-span-4">
                  <dt className="text-[12px] font-semibold text-muted">
                    Reason
                    {u.reason_code && <span className="text-ink">: {reasonLabel(u.reason_code)}</span>}
                  </dt>
                  <dd className="m-0 text-[14px]">{u.reason}</dd>
                </div>
              </dl>
              {!u.table_agrees && (
                <p role="alert" className="m-0 mt-3 text-[13px] font-medium text-crit">
                  The audit log and the emergency-approval record disagree. Treat this approval as unverified.
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
