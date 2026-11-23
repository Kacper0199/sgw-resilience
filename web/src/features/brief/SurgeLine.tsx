import { InfoTip } from "@/components/sgw";
import { activeSurges, useSurges } from "@/features/map/surges";
import { surgeMoment, surgeSpread } from "./surgeStory";

/** When county outage surges began and how many counties have one at the briefing time; a failed read says so instead of showing zero. */
export function SurgeLine({ asOf }: { asOf: string }) {
  const surges = useSurges(asOf, true);
  if (surges.isPending) return null;
  const story = surges.data
    ? surgeSpread(
        surges.data.surges.map((x) => x.detected_at),
        activeSurges(surges.data).map((x) => x.detected_at),
      )
    : null;
  return (
    <p className="m-0 pb-2 text-[13px] text-ink-2" data-testid="surge-line">
      {surges.error || !surges.data ? (
        <span className="text-muted">Outage surges aren't available yet.</span>
      ) : !story ? (
        <span className="text-muted">No county has an outage surge.</span>
      ) : (
        <span className="inline-flex flex-wrap items-center gap-x-1">
          {story.latest ? (
            <>
              Outage surges first detected in {story.first.count}{" "}
              {story.first.count === 1 ? "county" : "counties"} at {surgeMoment(story.first.at)};{" "}
              <b className="font-semibold text-ink tnum" data-testid="surge-count">
                {story.total}
              </b>{" "}
              of {surges.data.counties_monitored} by {surgeMoment(story.latest, story.first.at)}
            </>
          ) : (
            <>
              Outage surges in{" "}
              <b className="font-semibold text-ink tnum" data-testid="surge-count">
                {story.total}
              </b>{" "}
              of {surges.data.counties_monitored} counties since {surgeMoment(story.first.at)}
            </>
          )}
          <InfoTip term="outage_surge" />
        </span>
      )}
    </p>
  );
}
