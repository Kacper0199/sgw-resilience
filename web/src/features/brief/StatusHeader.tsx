import { InfoTip, StatusText } from "@/components/sgw";
import { formatAbsolute, formatETOn } from "@/lib/time";
import { formatWeekdayEt } from "./format";
import type { Brief } from "./types";

const upperFirst = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function StatusHeader({ brief }: { brief: Brief }) {
  const adv = brief.last_advisory;
  return (
    <div className="flex flex-col" data-testid="status-header">
      <div className="flex items-center gap-1">
        <StatusText
          level={brief.status.severity}
          label={brief.status.word}
          className="gap-3 text-[34px] leading-10 font-bold tracking-[-0.01em] [&_svg]:size-7"
        />
        <InfoTip term="brief_status" />
      </div>
      <p className="m-0 mt-2 text-[18px] leading-7 text-ink">{upperFirst(brief.status.reason)}</p>
      <p className="m-0 mt-2 text-[13px] text-muted">
        <span className="whitespace-nowrap">
          As of <b className="font-semibold text-ink">{formatAbsolute(brief.as_of)}</b>,{" "}
          {formatWeekdayEt(brief.as_of)}
        </span>
        <span>. </span>
        {adv ? (
          <span className="whitespace-nowrap" data-testid="advisory-line">
            {adv.next_utc ? (
              <>
                Latest advisory {formatETOn(adv.issued_utc, brief.as_of)}, next{" "}
                {formatETOn(adv.next_utc, brief.as_of)}
              </>
            ) : (
              <>Last advisory {formatETOn(adv.issued_utc, brief.as_of)} (final)</>
            )}
          </span>
        ) : (
          <span className="whitespace-nowrap">No advisory issued yet</span>
        )}
      </p>
    </div>
  );
}
