import {
  BookOpenText,
  Camera,
  CircleCheck,
  ClipboardCheck,
  CloudLightning,
  Droplets,
  Gauge,
  HardHat,
  type LucideIcon,
  MapIcon,
  MapPin,
  Warehouse,
  Waves,
  Zap,
} from "lucide-react";
import { Fragment } from "react";
import { Link } from "react-router";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Reference, ReferenceKind } from "../../agent-panel/types";
import { useProposals } from "../../decisions/useQueue";
import { chipText, type RefSegment, referenceHref, splitReferences } from "./references";

const ICON: Record<ReferenceKind, LucideIcon> = {
  decision: ClipboardCheck,
  asset: MapPin,
  county: MapIcon,
  zone: Droplets,
  advisory: CloudLightning,
  crew: HardHat,
  yard: Warehouse,
  readiness: Gauge,
  clause: BookOpenText,
  photo: Camera,
  surge: Zap,
  gauge: Waves,
  check: CircleCheck,
};

const CHIP =
  "inline-flex max-w-full items-center gap-1 rounded-[4px] bg-tint px-1 py-0.5 text-left align-baseline text-[13px] leading-[18px] text-ink transition-colors duration-120 hover:bg-blue-soft hover:text-blue-ink focus-visible:outline-2 focus-visible:outline-focus";

interface ChipProps {
  reference: Reference;
  text: string;
  before?: string;
  onClause?: (docId: string) => void;
}

/** An id in an answer, as a chip: kind icon, the words of the answer, the plain label on hover; it opens the page that shows it. */
export function RefChip({ reference, text, before = "", onClause }: ChipProps) {
  const proposals = useProposals().data;
  const href = referenceHref(
    reference,
    (caseId) => proposals?.find((p) => p.decision_case_id === caseId)?.proposal_id ?? null,
  );
  if (!href && reference.kind !== "clause") return <>{chipText(reference, text, before)}</>;
  const Icon = ICON[reference.kind];
  const shown = chipText(reference, text, before);
  const showsId = shown !== text && reference.kind !== "surge";
  const body = (
    <>
      <Icon aria-hidden className="size-3 shrink-0 text-muted" strokeWidth={1.75} />
      {shown}
    </>
  );
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {href ? (
          <Link
            to={href}
            className={CHIP}
            data-testid="ref-chip"
            data-kind={reference.kind}
            aria-label={shown}
          >
            {body}
          </Link>
        ) : (
          <button
            type="button"
            className={CHIP}
            data-testid="ref-chip"
            data-kind={reference.kind}
            aria-label={shown}
            onClick={() => onClause?.(reference.id)}
          >
            {body}
          </button>
        )}
      </TooltipTrigger>
      <TooltipContent>
        {showsId ? <span className="font-mono text-[11.5px]">{reference.id}</span> : reference.label}
      </TooltipContent>
    </Tooltip>
  );
}

/** Text already split into plain runs and chips (`splitReferences`, `splitAnswer`). */
export function RefSegments({
  segments,
  onClause,
}: {
  segments: readonly RefSegment[];
  onClause?: (docId: string) => void;
}) {
  return (
    <>
      {segments.map((s, i) =>
        s.kind === "text" ? (
          <Fragment key={s.at}>{s.text}</Fragment>
        ) : (
          <RefChip
            key={s.at}
            reference={s.ref}
            text={s.text}
            before={i > 0 ? segments[i - 1]?.text : ""}
            onClause={onClause}
          />
        ),
      )}
    </>
  );
}

/** Plain text with every reference it names shown as a chip. */
export function RefText({
  text,
  references,
  onClause,
}: {
  text: string;
  references: readonly Reference[];
  onClause?: (docId: string) => void;
}) {
  if (references.length === 0) return <>{text}</>;
  return <RefSegments segments={splitReferences(text, references)} onClause={onClause} />;
}
