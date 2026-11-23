import { ImageOff } from "lucide-react";
import { type MouseEvent, useState } from "react";
import { Link } from "react-router";
import type { AnswerPhoto } from "../../agent-panel/types";
import { PhotoPreview } from "../../crews/PhotoPreview";
import { isInternal } from "./AnswerLinks";

export const MAX_PHOTOS = 6;

const tileWidth = (n: number): number => (n <= 3 ? 168 : n === 4 ? 148 : 104);

const plainClick = (e: MouseEvent): boolean =>
  e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

function Tile({ photo, onOpen }: { photo: AnswerPhoto; onOpen: (id: string) => void }) {
  const [failed, setFailed] = useState(false);
  const open = (e: MouseEvent) => {
    if (!plainClick(e)) return;
    e.preventDefault();
    onOpen(photo.id);
  };
  return (
    <li className="min-w-0">
      <Link
        to={isInternal(photo.href) ? photo.href : "/crews?tab=photos"}
        onClick={open}
        aria-label={`Open photo: ${photo.caption}`}
        title={photo.caption}
        data-testid="answer-photo"
        className="group block overflow-hidden rounded-[8px] border border-hair bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        {failed ? (
          <span className="grid aspect-[4/3] place-items-center text-muted">
            <ImageOff aria-hidden className="size-5" />
          </span>
        ) : (
          <img
            src={photo.thumbUrl}
            alt={photo.caption}
            loading="lazy"
            onError={() => setFailed(true)}
            className="block aspect-[4/3] w-full object-cover transition-opacity duration-120 group-hover:opacity-90"
          />
        )}
      </Link>
    </li>
  );
}

/** Three to six damage photos as thumbnails; one opens the same photo detail as the Crews page, arrow keys move between them. */
export function PhotoStrip({ photos }: { photos: readonly AnswerPhoto[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const shown = photos.slice(0, MAX_PHOTOS);
  if (shown.length === 0) return null;
  const source = [...new Set(shown.map((p) => p.provenance).filter(Boolean))].join(", ");
  return (
    <section aria-label="Photos" className="flex flex-col gap-1.5" data-testid="answer-photos">
      <ul
        className="m-0 grid list-none gap-2 p-0"
        style={{
          gridTemplateColumns: `repeat(${shown.length}, minmax(0, ${tileWidth(shown.length)}px))`,
        }}
      >
        {shown.map((p) => (
          <Tile key={p.id} photo={p} onOpen={setOpenId} />
        ))}
      </ul>
      {source && <p className="m-0 text-[12px] text-muted">{source}</p>}
      <PhotoPreview ids={shown.map((p) => p.id)} openId={openId} onOpenChange={setOpenId} />
    </section>
  );
}
