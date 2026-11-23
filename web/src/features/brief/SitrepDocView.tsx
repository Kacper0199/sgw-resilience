import { PERSONAS } from "@/auth/personas";
import { InfoTip, StatusText, Tier } from "@/components/sgw";
import { formatAbsolute } from "@/lib/time";
import { formatWeekdayEt } from "./format";
import type { SitrepDoc } from "./types";

const who = (id: string) => PERSONAS.find((p) => p.user_id === id)?.title ?? id;

export function SitrepDocView({
  doc,
  label,
  draft,
  children,
}: {
  doc: SitrepDoc;
  label: string;
  draft: boolean;
  children?: React.ReactNode;
}) {
  return (
    <section
      aria-label={label}
      data-testid={doc.promoted_at ? "sitrep-current" : "sitrep-draft"}
      className="flex flex-col gap-3 border-t border-hair py-4 first:border-t-0 first:pt-0"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
        {draft ? (
          <StatusText level="elevated" label={label} className="text-[13px] font-semibold" />
        ) : (
          <h3 className="m-0 text-[13px] font-semibold">{label}</h3>
        )}
        <Tier tier={doc.tier} />
        <span className="text-muted">
          As of {formatAbsolute(doc.as_of_utc)}, {formatWeekdayEt(doc.as_of_utc)}
          {doc.promoted_by && doc.promoted_at && (
            <>
              {", "}confirmed by {who(doc.promoted_by)} at {formatAbsolute(doc.promoted_at)}
            </>
          )}
        </span>
      </header>
      <p className="m-0 text-reading" data-testid="sitrep-text">
        {doc.text}
      </p>
      {children}
      {doc.numbers.length > 0 && (
        <div>
          <h4 className="m-0 flex items-center gap-1 text-[13px] font-semibold">
            Sources for each number
            <InfoTip term="sitrep" />
          </h4>
          <ol
            aria-label={`Sources for each number (${doc.numbers.length})`}
            className="m-0 mt-1.5 list-decimal pl-5 text-[13px] text-muted"
          >
            {doc.numbers.map((n) => (
              <li key={n.label} className="py-0.5">
                <span className="text-ink">{n.label}</span>:{" "}
                <b className="font-semibold text-ink tnum">{n.value}</b>
                {n.source_id && <span className="font-mono text-[12px]"> ({n.source_id})</span>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
