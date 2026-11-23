import { ChevronRight, FlaskConical } from "lucide-react";
import { useId, useState } from "react";
import {
  CountBadge,
  EmptyState,
  InfoTip,
  LoadingState,
  SegmentedControl,
  StatusText,
} from "@/components/sgw";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { clauseName } from "@/lib/rules";
import { formatET, formatEtZ, formatRelative } from "@/lib/time";
import { DecisionLinks } from "./DecisionLinks";
import { percentPpm, zoneName } from "./format";
import { LoadFailed } from "./LoadFailed";
import type { ZoneNotice } from "./lifecycle";
import { NoticeStepper } from "./NoticeStepper";
import { ProbabilityStrip } from "./ProbabilityStrip";
import type { BwaAdvisory, BwaClause } from "./types";
import { useAdvisories, usePolicies, useRules, useZoneNotices } from "./useWater";

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Status word with its shape; the due time on a second line when there is one: "due in 1 h 17 m, at 09:17 ET (13:17Z)". */
export function NoticeStatus({
  status,
  dueUtc,
  now,
}: {
  status: ZoneNotice["status"];
  dueUtc?: string | null;
  now: string;
}) {
  return (
    <div className="text-[13px]">
      <StatusText level={status.level} label={status.label} />
      {dueUtc && (
        <p className="m-0 mt-0.5 text-muted">
          due {formatRelative(dueUtc, now)}, at{" "}
          <span className="font-mono text-[12px] tnum">{formatEtZ(dueUtc)}</span>
        </p>
      )}
    </div>
  );
}

/** Three plain numbers under the strip: chance the station loses power, low pressure if it does, faster hook-up. */
export function AdvisoryStats({
  advisory,
  fastest,
  fastestP,
}: {
  advisory: BwaAdvisory;
  fastest: number | undefined;
  fastestP: number | undefined;
}) {
  const [first, last] = [advisory.assessments[0], advisory.assessments[advisory.assessments.length - 1]];
  if (!first || !last) return null;
  const stats: [string, string][] = [
    [
      `${advisory.station_id} loses power`,
      `${percentPpm(first.power_loss_p_ppm)} → ${percentPpm(last.power_loss_p_ppm)}`,
    ],
    [
      "Low pressure after loss",
      `${percentPpm(first.breach_given_loss_p_ppm)} → ${percentPpm(last.breach_given_loss_p_ppm)}`,
    ],
    [`With a ${fastest}-min hookup`, fastestP === undefined ? "—" : percentPpm(fastestP)],
  ];
  return (
    <dl
      className="m-0 mt-3 grid grid-cols-3 gap-x-4 gap-y-1"
      data-testid="bwa-why"
      title="Previous → latest advisory"
    >
      {stats.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-[12px] text-muted">{label}</dt>
          <dd className="m-0 text-[16px] font-semibold tnum">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ClauseRow({ clause, defaultOpen }: { clause: BwaClause; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  return (
    <li className="border-t border-hair first:border-t-0" data-testid="clause-card">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 py-2.5 text-left"
      >
        <ChevronRight
          className={cn("size-4 text-muted transition-transform duration-[160ms]", open && "rotate-90")}
          aria-hidden
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="text-[13.5px] font-semibold">{clauseName(clause.clause_id)}</span>
          </TooltipTrigger>
          <TooltipContent>{clause.citation}</TooltipContent>
        </Tooltip>
        <span className="text-[13px] text-muted">{clause.state === "SC" ? "South Carolina" : "Georgia"}</span>
      </button>
      <div id={bodyId} hidden={!open} className="pb-3 pl-6 text-[13.5px]">
        <p className="m-0">{sentence(clause.summary)}</p>
        {clause.sop && (
          <p className="m-0 mt-1 text-[12.5px] text-muted">
            {`SGW procedure ${clause.sop.doc_id}, section ${clause.sop.section}`}
          </p>
        )}
      </div>
    </li>
  );
}

/** The chance of low pressure from the previous to the latest advisory against the notice trigger, with the three numbers behind it. */
export function AdvisoryForecast({
  advisory,
  threshold,
  width,
  stats = true,
}: {
  advisory: BwaAdvisory;
  threshold: number | undefined;
  width: number;
  stats?: boolean;
}) {
  const [first, last] = [advisory.assessments[0], advisory.assessments[advisory.assessments.length - 1]];
  if (!first || !last) return null;
  const fastest = [...advisory.sensitivity].sort((a, b) => a.hookup_lag_min - b.hookup_lag_min)[0];
  return (
    <>
      <p className="m-0 flex items-center gap-1 text-[13px] text-muted">
        Chance of low pressure before landfall <InfoTip term="breach_chance" />
      </p>
      <ProbabilityStrip
        from={{ label: formatET(first.issued_utc), ppm: first.breach_p_ppm }}
        to={{ label: formatET(last.issued_utc), ppm: last.breach_p_ppm }}
        threshold={threshold}
        width={width}
      />
      {stats && (
        <AdvisoryStats
          advisory={advisory}
          fastest={fastest?.hookup_lag_min}
          fastestP={fastest?.breach_p_ppm}
        />
      )}
    </>
  );
}

const asClauseIds = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

/** The clauses a zone's notice rests on: its advisories' own, else those the rule that raised the decision names. */
function citedClauseIds(advisories: BwaAdvisory[], notice: ZoneNotice): string[] {
  const fromAdvisories = advisories.flatMap((a) => a.clause_ids);
  const params = notice.decision?.params;
  const fromRule = params
    ? [params.clause, params.floor_clause, ...asClauseIds(params.clauses_met), params.pending_clause].filter(
        (v): v is string => typeof v === "string",
      )
    : [];
  return [...new Set([...fromAdvisories, ...fromRule])];
}

function NoticeRow({
  notice,
  advisories,
  clauses,
  threshold,
  now,
  defaultOpen,
}: {
  notice: ZoneNotice;
  advisories: BwaAdvisory[];
  clauses: BwaClause[];
  threshold: number | undefined;
  now: string;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const name = zoneName(notice.zoneId);
  const forecasts = advisories.filter((a) => a.assessments.length > 0);
  const cited = citedClauseIds(advisories, notice)
    .map((id) => clauses.find((c) => c.clause_id === id))
    .filter((c): c is BwaClause => !!c);
  const hasDetail = forecasts.length > 0 || cited.length > 0;
  const decisionTitle = notice.current === "lift" ? "Lift the boil-water notice" : "Boil-water notice";
  return (
    <section className="border-b border-hair px-8 py-3" data-testid="bwa-row" aria-label={`${name} notice`}>
      <div className="grid items-center gap-x-8 gap-y-3 min-[1100px]:grid-cols-[minmax(190px,240px)_minmax(0,1fr)_132px]">
        <div className="min-w-0">
          <h3 className="m-0 mb-1 text-[16px] leading-6 font-bold">{name}</h3>
          <NoticeStatus status={notice.status} dueUtc={notice.dueUtc} now={now} />
        </div>
        <NoticeStepper notice={notice} zoneLabel={name} />
        <div className="min-[1100px]:text-right">
          {notice.decision && (
            <DecisionLinks proposalId={notice.decision.proposal_id} title={`${decisionTitle}, ${name}`} />
          )}
        </div>
      </div>
      {hasDetail && (
        <>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((o) => !o)}
            className="mt-2 flex items-center gap-1 text-[13px] font-semibold text-blue-ink hover:underline"
          >
            <ChevronRight
              className={cn("size-4 transition-transform duration-[160ms]", open && "rotate-90")}
              aria-hidden
            />
            Details
          </button>
          <div id={bodyId} hidden={!open} className="mt-3 grid gap-x-10 gap-y-6 min-[1100px]:grid-cols-2">
            {forecasts.length > 0 && (
              <div className="min-w-0">
                {forecasts.map((a) => (
                  <div key={a.advisory_id} className="mb-4 last:mb-0">
                    <AdvisoryForecast advisory={a} threshold={threshold} width={500} />
                  </div>
                ))}
              </div>
            )}
            <div className="min-w-0">
              <h4 className="m-0 mb-1.5 text-[16px] font-bold">Rules cited</h4>
              <ul className="m-0 list-none p-0">
                {cited.map((c, i) => (
                  <ClauseRow key={c.clause_id} clause={c} defaultOpen={i === 0} />
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function RuleBook({ clauses }: { clauses: BwaClause[] }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"SC" | "GA">("SC");
  const list = clauses.filter((c) => c.state === state);
  return (
    <div className="px-8 py-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 text-[13px] font-semibold text-blue-ink hover:underline"
      >
        <ChevronRight
          className={cn("size-4 transition-transform duration-[160ms]", open && "rotate-90")}
          aria-hidden
        />
        All rules
        <CountBadge count={clauses.length} />
      </button>
      {open && (
        <div className="mt-3 max-w-[760px]">
          <SegmentedControl
            label="Rules by state"
            value={state}
            onValueChange={setState}
            options={[
              { value: "SC", label: `South Carolina ${clauses.filter((c) => c.state === "SC").length}` },
              { value: "GA", label: `Georgia ${clauses.filter((c) => c.state === "GA").length}` },
            ]}
          />
          <ul className="m-0 mt-2 list-none p-0">
            {list.map((c) => (
              <ClauseRow key={c.clause_id} clause={c} defaultOpen={false} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The boil-water notices tab: one line per zone with its notice, the five steps from due to lifted, then the rule book. */
export function AdvisoryContainer({ now }: { now: string }) {
  const adv = useAdvisories();
  const rules = useRules();
  const policies = usePolicies();
  const state = useZoneNotices();
  const threshold = policies.data?.find((p) => p.key === "policy_pre_landfall_breach_p")?.value;
  const clauses = rules.data?.clauses ?? [];
  const failure = adv.error ?? state.error;
  if (failure) {
    return (
      <LoadFailed
        thing="boil-water notices"
        icon={FlaskConical}
        error={failure}
        onRetry={() => void adv.refetch()}
      />
    );
  }
  if (state.isPending) return <LoadingState label="Loading boil-water notices…" rows={3} />;
  if (state.notices.length === 0) {
    return <EmptyState icon={FlaskConical} title="No boil-water notice is due or in force." />;
  }
  return (
    <div>
      {adv.data?.forecasts_withheld && (
        <p className="m-0 px-8 pt-4 text-[13px] text-muted">
          Pressure forecasts are shown to the water team.
        </p>
      )}
      {state.notices.map((n) => (
        <NoticeRow
          key={n.zoneId}
          notice={n}
          advisories={(adv.data?.advisories ?? []).filter((a) => a.zone_id === n.zoneId)}
          clauses={clauses}
          threshold={typeof threshold === "number" ? threshold : undefined}
          now={now}
          defaultOpen={state.notices.length === 1}
        />
      ))}
      {clauses.length > 0 && <RuleBook clauses={clauses} />}
    </div>
  );
}
