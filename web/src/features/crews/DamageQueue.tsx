import { ImageOff, ScanSearch } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useState } from "react";
import { CountBadge, EmptyState, LoadingState, SegmentedControl, StatusText } from "@/components/sgw";
import { ReasonTip } from "@/features/decisions/ReasonTip";
import { LoadFailed } from "@/features/water/LoadFailed";
import { plainIds } from "@/lib/names";
import { useBeforeLandfall } from "./landfall";
import { PhotoPreview, REVIEW } from "./PhotoPreview";
import { thumbUrl } from "./thumbs";
import type { DamageCase, DamagePhoto, EvalRow, DamageQueue as Queue } from "./types";
import { useDamageQueue, useLadiEvaluation } from "./useCrews";

const SEVERITY = { slight: 1, moderate: 2, extensive: 3, complete: 4 } as const;
const STATE_LABEL: Record<DamageCase["damage_state"], string> = {
  slight: "Slight damage",
  moderate: "Moderate damage",
  extensive: "Extensive damage",
  complete: "Complete damage",
};

const SIGNAL: Record<string, string> = {
  trees_damage: "Tree damage",
  buildings_affected_or_greater: "Building damage (any)",
  buildings_minor_or_greater: "Building damage (minor or worse)",
  debris_any: "Debris",
  flooding_any: "Flooding",
  flooding_structures: "Flooded buildings",
  roads_damage: "Road damage",
};

const ACTION: Record<string, string> = {
  "line-clearance crew": "Send a line-clearance crew",
  "raise restoration priority": "Raise restoration priority",
  "access check (routing penalty)": "Check road access first",
};

const ORDINAL = ["", "1st", "2nd", "3rd"];
const ordinal = (n: number) => ORDINAL[n] ?? `${n}th`;
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const photoName = (imageId: string) => imageId.replace("ladi-v2-", "");

/** "FDR-AIK-2219-S2" reads as "feeder 2219, section 2": where the damage is. */
const sectionPlace = (sectionId: string): string => {
  const m = /^(.*)-S(\d+)$/.exec(sectionId);
  return m ? `${plainIds(m[1] ?? sectionId)}, section ${m[2]}` : plainIds(sectionId);
};

function Thumb({
  imageId,
  size = 48,
  onOpen,
}: {
  imageId: string;
  size?: number;
  onOpen: (id: string) => void;
}) {
  const url = thumbUrl(imageId);
  const [failed, setFailed] = useState(false);
  return (
    <button
      type="button"
      onClick={() => onOpen(imageId)}
      aria-label={`Open photo ${photoName(imageId)}`}
      className="shrink-0 cursor-zoom-in rounded-sm outline-offset-2 hover:opacity-85"
      data-testid="damage-thumb"
    >
      {url && !failed ? (
        <img
          src={url}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          onError={() => setFailed(true)}
          className="block rounded-sm object-cover ring-1 ring-hair ring-inset"
          style={{ width: size, height: size }}
        />
      ) : (
        <span
          className="grid place-items-center rounded-sm bg-surface-3 text-muted ring-1 ring-hair ring-inset"
          style={{ width: size, height: size }}
        >
          <ImageOff className="size-4" aria-hidden />
        </span>
      )}
    </button>
  );
}

/** The damaged case with the highest volunteer-labelled severity should rank first; say so when it does not. */
export function visibleMiss(cases: DamageCase[]): { text: string; caseId: string } | null {
  const damaged = cases.filter((c) => SEVERITY[c.damage_state] >= 2);
  const worst = [...damaged].sort((a, b) => SEVERITY[b.damage_state] - SEVERITY[a.damage_state])[0];
  if (!worst) return null;
  const rank = [...damaged].sort((a, b) => a.case_rank - b.case_rank).indexOf(worst) + 1;
  if (rank === 1) return null;
  return {
    caseId: worst.case_id,
    text: `The worst-damaged case (${worst.damage_state}, section ${worst.section_id}) ranks only ${ordinal(rank)} of ${damaged.length} damaged cases.`,
  };
}

function Band({ label, n }: { label: string; n: number }) {
  return (
    <li
      aria-hidden
      className="flex items-center gap-2 border-b border-hair bg-surface-2 px-8 py-2 text-[13px] font-semibold text-ink-2"
    >
      {label}
      <CountBadge count={n} />
    </li>
  );
}

function CaseRow({ c, miss, onOpen }: { c: DamageCase; miss: boolean; onOpen: (id: string) => void }) {
  return (
    <li
      className="grid grid-cols-[28px_minmax(220px,360px)_auto] items-center gap-x-4 border-b border-hair px-8 py-2.5"
      data-testid="damage-case"
      data-miss={miss}
    >
      <span
        className="text-[13px] font-semibold text-muted tnum"
        title={`Rank ${c.case_rank}, model score ${c.case_score.toFixed(2)}`}
      >
        {c.case_rank}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5 leading-tight">
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[14px] font-medium">
          {c.photo_ids[0] ? (
            <button
              type="button"
              className="cursor-pointer border-0 bg-transparent p-0 text-left font-medium text-ink hover:underline"
              onClick={() => onOpen(c.photo_ids[0] as string)}
            >
              {STATE_LABEL[c.damage_state]}, {sectionPlace(c.section_id)}
            </button>
          ) : (
            `${STATE_LABEL[c.damage_state]}, ${sectionPlace(c.section_id)}`
          )}
          {miss && <StatusText level="elevated" label="Model ranked this too low" className="text-[12px]" />}
        </span>
        <span className="text-[12px] text-muted" data-testid="case-review">
          {REVIEW[c.status] ?? c.status}
        </span>
      </span>
      <fieldset className="m-0 flex gap-1 border-0 p-0">
        <legend className="sr-only">Photos in this case</legend>
        {c.photo_ids.map((id) => (
          <Thumb key={id} imageId={id} onOpen={onOpen} />
        ))}
      </fieldset>
    </li>
  );
}

function ModelNotes({ q, refScore }: { q: Queue; refScore: EvalRow | undefined }) {
  const miss = visibleMiss(q.cases);
  const o = q.seeded_order;
  const checksPass = o.tier_violations === 0 && o.structural_above_all_control_groups;
  return (
    <ReasonTip label="About the damage model" title="About the damage model">
      <p className="m-0" data-testid="damage-note">
        {sentence(q.imagery_note)}. Cases are ranked by the model's damage score (hover a rank number to see
        it). A person confirms or rejects every photo before it changes a plan.
      </p>
      {miss && (
        <p className="m-0" data-testid="visible-miss">
          <span className="font-semibold text-ink">One clear miss. </span>
          {miss.text} The model doesn't reliably tell the four damage levels apart:{" "}
          {o.ladder_discordant_pairs} of {o.ladder_pairs} pairs are in the wrong order.
        </p>
      )}
      <p className="m-0" data-testid="two-tier">
        {checksPass ? "Two checks pass: " : "Not every check passes: "}
        every moderate-or-worse case scores above the slight cases and above every no-damage group (lowest{" "}
        {o.structural_min_score.toFixed(2)}, controls up to {o.control_group_max_score.toFixed(2)}).
      </p>
      <p className="m-0">
        {`Photos: LADI v2 (Civil Air Patrol, MIT Lincoln Laboratory), CC BY 4.0${refScore ? `; published score ${refScore.value.toFixed(1)} (mAP, not measured by SGW)` : ""}`}
      </p>
    </ReasonTip>
  );
}

function Cases({ q, onOpen }: { q: Queue; onOpen: (id: string) => void }) {
  const miss = visibleMiss(q.cases);
  const sorted = [...q.cases].sort((a, b) => a.case_rank - b.case_rank);
  const serious = sorted.filter((c) => SEVERITY[c.damage_state] >= 2);
  const slight = sorted.filter((c) => SEVERITY[c.damage_state] < 2);
  return (
    <ul className="m-0 list-none p-0" aria-label="Damage cases by score">
      <Band label="Moderate or worse" n={serious.length} />
      {serious.map((c) => (
        <CaseRow key={c.case_id} c={c} miss={c.case_id === miss?.caseId} onOpen={onOpen} />
      ))}
      <Band label="Slight" n={slight.length} />
      {slight.map((c) => (
        <CaseRow key={c.case_id} c={c} miss={false} onOpen={onOpen} />
      ))}
    </ul>
  );
}

export const topPhotos = (rows: DamagePhoto[]) => rows.filter((r) => r.rank <= 12);

function Photos({ rows, onOpen }: { rows: DamagePhoto[]; onOpen: (id: string) => void }) {
  const top = topPhotos(rows);
  return (
    <ul className="m-0 list-none p-0" aria-label="Highest-scoring photos">
      {top.map((r) => (
        <li
          key={r.image_id}
          className="grid grid-cols-[28px_56px_minmax(0,1fr)] items-center gap-x-3 border-b border-hair px-8 py-2"
          data-testid="damage-photo"
        >
          <span
            className="text-[13px] font-semibold text-muted tnum"
            title={`Rank ${r.rank}, model score ${r.triage_score.toFixed(2)}`}
          >
            {r.rank}
          </span>
          <Thumb imageId={r.image_id} size={56} onOpen={onOpen} />
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="text-[13px]">{r.signals.map((s) => SIGNAL[s] ?? s).join(", ")}</span>
            <span className="text-[12px] text-muted">
              {r.human_only.length > 0
                ? r.human_only[0]
                : r.suggested_actions.map((a) => ACTION[a] ?? a).join(", ")}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The photos in the order they are on screen, so the arrow keys in the preview follow the list. */
export function previewOrder(q: Queue, view: "cases" | "photos"): string[] {
  if (view === "photos") return topPhotos(q.rows).map((r) => r.image_id);
  const sorted = [...q.cases].sort((a, b) => a.case_rank - b.case_rank);
  const serious = sorted.filter((c) => SEVERITY[c.damage_state] >= 2);
  const slight = sorted.filter((c) => SEVERITY[c.damage_state] < 2);
  return [...serious, ...slight].flatMap((c) => c.photo_ids);
}

const referenceRow = (rows: EvalRow[] | undefined) =>
  rows?.find((r) => r.metric === "ladi_v2.small_reference.test_map");

/** The damage photos tab: cases ranked by score, or the top photos, with the model's honest limits first. */
export function DamageQueue() {
  const q = useDamageQueue();
  const ladi = useLadiEvaluation();
  const [view, setView] = useState<"cases" | "photos">("cases");
  const [openId, setPhoto] = useQueryState("photo", parseAsString.withOptions({ history: "replace" }));
  const setOpenId = (id: string | null) => void setPhoto(id);
  const ref = referenceRow(ladi.data?.metrics);
  const early = useBeforeLandfall();
  if (early)
    return (
      <>
        <EmptyState
          icon={ScanSearch}
          title="No damage photos yet."
          description="Field photos come in after landfall."
        />
        <PhotoPreview ids={openId ? [openId] : []} openId={openId} onOpenChange={setOpenId} />
      </>
    );
  if (q.error)
    return (
      <LoadFailed thing="damage photos" icon={ScanSearch} error={q.error} onRetry={() => void q.refetch()} />
    );
  if (q.isPending) return <LoadingState label="Loading damage photos…" rows={4} />;
  if (q.data.cases.length === 0) {
    return (
      <EmptyState
        icon={ScanSearch}
        title="No photos are waiting for review."
        description="Photos appear here after the damage model scores them."
      />
    );
  }
  return (
    <>
      <div className="flex flex-wrap items-center gap-3 px-8 py-3">
        <SegmentedControl
          label="View"
          value={view}
          onValueChange={setView}
          options={[
            { value: "cases", label: "Cases" },
            { value: "photos", label: "Photos" },
          ]}
        />
        <span className="flex items-center gap-1 text-[13px] text-muted tnum">
          {q.data.cases.length} cases, {q.data.total_photos} photos
          <ModelNotes q={q.data} refScore={ref} />
        </span>
      </div>
      {view === "cases" ? (
        <Cases q={q.data} onOpen={setOpenId} />
      ) : (
        <Photos rows={q.data.rows} onOpen={setOpenId} />
      )}
      <PhotoPreview ids={previewOrder(q.data, view)} openId={openId} onOpenChange={setOpenId} />
    </>
  );
}
