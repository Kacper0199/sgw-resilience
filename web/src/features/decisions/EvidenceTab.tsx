import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { plainAdvisory } from "@/lib/advisory";
import type { Asset, ProposalCard } from "@/lib/api";
import { assetName, plainIds } from "@/lib/names";
import { formatDayET, formatET, formatRecorded } from "@/lib/time";
import { decisionTitle } from "./actionTypes";
import { CeBreakdown } from "./CeBreakdown";
import { PaneSection } from "./PaneSection";
import { type EvidenceRecord, useAssetIndex, useEvidence } from "./queries";

const KIND_LABEL: Record<string, string> = {
  observation: "Measurement",
  forecast: "Forecast",
  rule: "Rule",
  document: "Document",
  record: "Record",
  etr_estimate: "Restoration estimate",
};

const plainSource = (source: string) =>
  source
    .replace(/^WP-\d+[a-z]? ETR model/, "Restoration model")
    .replace(/^WP-\d+[a-z]?\s+/, "")
    .replace(/^R\d{2}\s+[A-Z]{1,3}-\d+\s+assumption/, "SGW assumption")
    .replace(/,\s*R\d{2}(?:\s+[A-Z]{1,3}-?\d*)?(?=\))/g, "")
    .replace(/\s*\((?:WP-\d+[a-z]?|R\d{2}|D-\d{3})(?:[ ,;/]+[A-Z0-9][\w.-]*)*\)/g, "");

const plainTitle = (title: string) =>
  plainIds(plainAdvisory(title.replace(/\s*\((?:DC-[A-Z0-9-]+)(?:, [A-Z]\d)?\)/g, "")));

const targetName = (a: Asset): string => {
  const name = (a as { name?: string }).name?.replace(/\s*\(synthetic\)/, "");
  return decisionTitle(!name || name.includes(a.asset_id) ? assetName(a.asset_id) : plainIds(name));
};

const kindSuffix = (a: Asset): string | null => {
  const kind = a.kind.replace(/_/g, " ");
  const noun = kind.split(" ").at(-1) ?? kind;
  return targetName(a).toLowerCase().includes(noun) ? null : kind;
};

const when = (iso: string) => `${formatDayET(iso)}, ${formatET(iso)}`;

/** The global ETR a publish decision puts out: the likely 90% restored time and its middle range. */
function EstimateToPublish({ params }: { params: Record<string, unknown> }) {
  const p50 = typeof params.p50_utc === "string" ? params.p50_utc : null;
  if (!p50) return null;
  const p25 = typeof params.p25_utc === "string" ? params.p25_utc : null;
  const p75 = typeof params.p75_utc === "string" ? params.p75_utc : null;
  return (
    <PaneSection title="Estimate to publish">
      <p className="m-0 text-[13px] font-medium" data-testid="etr-to-publish">
        90% restored {when(p50)}
      </p>
      {p25 && p75 && (
        <p className="m-0 text-[12px] text-muted">
          Middle half {when(p25)} to {when(p75)}
        </p>
      )}
    </PaneSection>
  );
}

function RecordRow({ id, record }: { id: string; record: EvidenceRecord | undefined }) {
  const known = record?.recorded && !record.withheld && record.title;
  const kind = record?.kind ? (KIND_LABEL[record.kind] ?? record.kind.replace(/_/g, " ")) : null;
  const detail = [kind, record?.as_of_utc ? formatRecorded(record.as_of_utc) : null].filter(Boolean);
  return (
    <li className="border-b border-hair py-2.5 last:border-b-0" data-testid="evidence-item">
      <p className="m-0 text-[13px] font-medium">
        {known ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span>{plainTitle(record.title ?? "")}</span>
            </TooltipTrigger>
            <TooltipContent>{record.source ? `${plainSource(record.source)}, ${id}` : id}</TooltipContent>
          </Tooltip>
        ) : record?.withheld ? (
          "Record withheld for your role"
        ) : (
          <>
            <span title={id}>Record not kept</span>
          </>
        )}
      </p>
      <p className="m-0 text-[12px] text-muted">
        {detail.length > 0 ? detail.join(", ") : "Details weren't kept for this record."}
      </p>
    </li>
  );
}

export function EvidenceTab({ card }: { card: ProposalCard }) {
  const assets = useAssetIndex();
  const evidence = useEvidence(card.proposal_id);
  const byId = new Map((evidence.data ?? []).map((r) => [r.id, r]));
  return (
    <div className="flex flex-col" data-testid="evidence">
      {card.action_type === "publish_global_etr" && <EstimateToPublish params={card.params} />}
      <PaneSection title="Attached records" info="evidence">
        {card.evidence_ids.length === 0 ? (
          <p className="m-0 text-[13px] text-muted">No records attached.</p>
        ) : (
          <ul className="m-0 list-none p-0">
            {card.evidence_ids.map((id) => (
              <RecordRow key={id} id={id} record={byId.get(id)} />
            ))}
          </ul>
        )}
      </PaneSection>
      <CeBreakdown card={card} />
      {card.target_ids.length > 0 && (
        <PaneSection title="Targets">
          <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 pb-1 text-[13px]">
            {card.target_ids.map((id) => (
              <li key={id} title={id}>
                {assets.get(id) ? targetName(assets.get(id) as Asset) : assetName(id)}
                {assets.get(id) && kindSuffix(assets.get(id) as Asset) && (
                  <span className="text-muted">, {kindSuffix(assets.get(id) as Asset)}</span>
                )}
              </li>
            ))}
          </ul>
        </PaneSection>
      )}
    </div>
  );
}
