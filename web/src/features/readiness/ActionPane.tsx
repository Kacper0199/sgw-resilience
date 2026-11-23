import type * as React from "react";
import { FUNCTION_LABEL } from "@/auth/personas";
import { TierBadge } from "@/components/sgw";
import { plainIds } from "@/lib/names";
import { Fact } from "./HazardLayout";
import { shortText } from "./hazardModel";
import type { HazardAction } from "./hazardTypes";

const signersText = (a: HazardAction) =>
  a.signers.length > 0 ? a.signers.map((f) => FUNCTION_LABEL[f]).join(" + ") : "Outside SGW";

interface ActionPaneProps {
  actions: HazardAction[];
  appliesTo: string;
  asOf: string;
  children?: React.ReactNode;
}

/** The step the model recommends, the approval it needs and who would sign it; the other protocol steps one line each. Read-only. */
export function ActionPane({ actions, appliesTo, asOf, children }: ActionPaneProps) {
  const [first, ...rest] = actions;
  if (!first) return null;
  return (
    <div className="px-6 py-5">
      <p className="m-0 text-[12px] font-semibold text-muted">Recommended action</p>
      <h2 className="m-0 mt-1 text-[18px] leading-6 font-semibold" data-testid="action-title">
        {plainIds(first.text)}
      </h2>
      <dl className="m-0 mt-4 grid grid-cols-2 gap-x-6 gap-y-3">
        <Fact label="Approval">
          <TierBadge tier={first.tier} />
        </Fact>
        <Fact label="Signs">
          <span data-testid="action-signers">{signersText(first)}</span>
        </Fact>
        <Fact label="Applies to">{appliesTo}</Fact>
        <Fact label="As of">{asOf}</Fact>
      </dl>
      {children}
      {rest.length > 0 && (
        <>
          <h3 className="m-0 mt-5 border-b border-hair pb-2 text-[15px] leading-5 font-bold">Also</h3>
          <ul className="m-0 list-none p-0" data-testid="action-also">
            {rest.map((a) => (
              <li
                key={a.action_id}
                className="flex items-start justify-between gap-3 border-b border-hair py-2 text-[13px] leading-[18px] last:border-b-0"
              >
                <span className={a.recommended ? "" : "text-muted"}>
                  {!a.recommended && <span className="font-semibold">Not recommended: </span>}
                  {plainIds(shortText(a))}
                </span>
                <TierBadge tier={a.tier} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
