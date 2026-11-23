import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ImageOff } from "lucide-react";
import { useState } from "react";
import { LoadingState } from "@/components/sgw";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import type { components } from "@/contracts/api.gen";
import { ReasonTip } from "@/features/decisions/ReasonTip";
import { get } from "@/lib/api";

type Detail = components["schemas"]["DamagePhotoDetail"];

export const LABEL: Record<string, string> = {
  trees_damage: "Tree damage",
  buildings_affected_or_greater: "Building damage (any)",
  buildings_minor_or_greater: "Building damage (minor or worse)",
  debris_any: "Debris",
  flooding_any: "Flooding",
  flooding_structures: "Flooded buildings",
  roads_damage: "Road damage",
  bridges_any: "Bridge",
};

export const REVIEW: Record<string, string> = {
  awaiting_review: "Waiting for review",
  confirmed: "Confirmed",
  rejected: "Rejected",
};

const ACTION: Record<string, string> = {
  "line-clearance crew": "Send a line-clearance crew",
  "raise restoration priority": "Raise restoration priority",
  "access check (routing penalty)": "Check road access first",
};

const pct = (x: number) => `${Math.round(x * 100)}%`;

const usePhoto = (id: string | null) =>
  useQuery({
    queryKey: ["damage", "photo", id],
    queryFn: () => get<Detail>(`/api/damage/photos/${encodeURIComponent(id ?? "")}`),
    enabled: id !== null,
    staleTime: Number.POSITIVE_INFINITY,
  });

function Image({ d }: { d: Detail }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className="grid h-full min-h-60 place-items-center bg-surface-3 text-muted">
        <span className="flex items-center gap-2 text-[13px]">
          <ImageOff className="size-4" aria-hidden /> Photo not available
        </span>
      </div>
    );
  }
  return (
    <img
      key={d.image_id}
      src={d.image_url}
      alt={`Aerial photo, rank ${d.rank}: ${d.signals.map((s) => LABEL[s] ?? s).join(", ") || "no damage signal"}`}
      onError={() => setFailed(true)}
      className="block max-h-[min(70vh,640px)] w-full bg-surface-3 object-contain"
      data-testid="photo-full"
    />
  );
}

function Facts({ d }: { d: Detail }) {
  const action = d.human_only[0] ?? d.suggested_actions.map((a) => ACTION[a] ?? a).join(", ");
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex items-baseline gap-3">
        <span className="text-[28px] leading-none font-semibold tnum">{d.triage_score.toFixed(2)}</span>
        <span className="text-[13px] text-muted">damage score, photo {d.rank} in the review order</span>
      </div>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="What the model sees">
        {d.labels.map((l) => (
          <li key={l.label} className="grid grid-cols-[minmax(0,1fr)_44px] items-center gap-x-3 text-[13px]">
            <span className={l.score >= 0.5 ? "font-semibold text-ink" : "text-muted"}>
              {LABEL[l.label] ?? l.label}
            </span>
            <span className="text-end tnum">{pct(l.score)}</span>
            <span aria-hidden className="col-span-2 h-1 rounded-full bg-[var(--chart-track)]">
              <span className="block h-1 rounded-full bg-[var(--chart-1)]" style={{ width: pct(l.score) }} />
            </span>
          </li>
        ))}
      </ul>
      {action && <p className="m-0 text-[13px]">{action}</p>}
      <p className="m-0 text-[13px] text-muted">{REVIEW[d.status] ?? d.status}</p>
    </div>
  );
}

interface Props {
  ids: string[];
  openId: string | null;
  onOpenChange: (id: string | null) => void;
}

/** The photo preview: the full-size photo (or its thumbnail when the photos are not downloaded), the model's
 *  scores in plain words, arrow keys to move through the list, Esc to close. No external links. */
export function PhotoPreview({ ids, openId, onOpenChange }: Props) {
  const q = usePhoto(openId);
  const at = openId ? ids.indexOf(openId) : -1;
  const go = (step: number) => {
    if (at < 0 || ids.length < 2) return;
    onOpenChange(ids[(at + step + ids.length) % ids.length] ?? null);
  };
  return (
    <Dialog open={openId !== null} onOpenChange={(open) => !open && onOpenChange(null)}>
      <DialogContent
        className="w-[min(980px,calc(100vw-32px))]"
        data-testid="photo-preview"
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") go(1);
          if (e.key === "ArrowLeft") go(-1);
        }}
      >
        <div className="flex items-center gap-2 pr-10">
          <DialogTitle className="text-[18px]">Damage photo</DialogTitle>
          <ReasonTip label="About this photo" title="About this photo">
            <p className="m-0">
              LADI v2 aerial photo (Civil Air Patrol imagery, MIT Lincoln Laboratory), CC BY 4.0. Scores from
              the LADI v2 reference classifier. A person reviews every photo before it changes a plan.
            </p>
          </ReasonTip>
          {ids.length > 1 && at >= 0 && (
            <span className="ml-auto flex items-center gap-1 text-[13px] text-muted tnum">
              <IconButton
                small
                label="Previous photo"
                icon={<ChevronLeft aria-hidden />}
                onClick={() => go(-1)}
              />
              {at + 1} of {ids.length}
              <IconButton
                small
                label="Next photo"
                icon={<ChevronRight aria-hidden />}
                onClick={() => go(1)}
              />
            </span>
          )}
        </div>
        <DialogDescription className="sr-only">
          The photo with the damage model's scores. Left and right arrow keys move between photos.
        </DialogDescription>
        {q.error ? (
          <p className="m-0 text-[13px]">This photo didn't load.</p>
        ) : !q.data ? (
          <LoadingState label="Loading photo…" rows={3} />
        ) : (
          <div className="grid gap-6 min-[820px]:grid-cols-[minmax(0,1fr)_260px]">
            <Image d={q.data} />
            <Facts d={q.data} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
