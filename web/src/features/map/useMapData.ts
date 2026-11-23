import { useMemo } from "react";
import { useScenario, useScenarioNow } from "@/sse/useScenarioNow";
import { useQueue } from "../decisions/useQueue";
import { buildStops, placeIdsOf, type SequenceStep, sequenceOf, unplacedSteps } from "./chain";
import { advisoryAt, useAdvisories, useAdvisoryHazard, useAssets, useCountyRisk } from "./data";
import { assetPosition, type CountyValue, domainOf } from "./layerData";
import type { CountyColour } from "./layers";
import type { StepStop } from "./Overlays";
import { observedAt, useObserved } from "./observed";
import { outagesByCounty, useCountyOutages } from "./outagesNow";
import { issuedKey, stormGeometry, useNhcProducts } from "./storm";
import { activeSurges, surgeStarts, useSurges } from "./surges";
import { useBasemap } from "./useBasemap";

const DAY_MS = 86_400_000;

/** The clock is inside the scenario on screen: right after a load the stream's clock can lead the scenario read. */
export function withinPeriod(
  period: { start_utc: string; end_utc: string } | null | undefined,
  now: string | null,
) {
  if (!period || now === null) return true;
  const t = Date.parse(now);
  return t >= Date.parse(period.start_utc) - DAY_MS && t <= Date.parse(period.end_utc) + DAY_MS;
}

interface Input {
  selectedProposalId: string | null;
  selectedAssetIds?: ReadonlySet<string>;
  advisoryLabel?: string | null;
  county: CountyColour;
  /** Any observed layer (warnings, gauges, airport wind) is on: only then are observations fetched. */
  observed?: boolean;
  /** The outage surge layer is on. */
  surges?: boolean;
  /** A scripted exercise: no risk forecast to read. */
  scripted?: boolean;
}

/** Everything the map draws, derived from the API reads: one place, so the preview and the page cannot disagree. */
export function useMapData({
  selectedProposalId,
  selectedAssetIds,
  advisoryLabel,
  county,
  observed = false,
  surges = false,
  scripted = false,
}: Input) {
  const assets = useAssets();
  const advisories = useAdvisories();
  const now = useScenarioNow();
  const basemap = useBasemap();
  const products = useNhcProducts();
  const current = advisoryAt(advisories.data ?? [], now);
  const period = useScenario().data?.period;
  const label = withinPeriod(period, now) ? (advisoryLabel ?? current?.advisory_label ?? null) : null;
  const hazard = useAdvisoryHazard(label);
  const issued = useMemo(
    () => (advisories.data ?? []).filter((a) => now === null || Date.parse(a.issued_utc) <= Date.parse(now)),
    [advisories.data, now],
  );
  const risk = useCountyRisk(scripted ? null : (hazard.data?.issued_utc ?? null));
  const live = label !== null && label === current?.advisory_label;
  const observedTime = observedAt(live, now, hazard.data?.issued_utc ?? null);
  const observations = useObserved(observedTime, observed);
  const surgeReport = useSurges(observedTime, surges);
  const surgeList = useMemo(() => activeSurges(surgeReport.data), [surgeReport.data]);
  const outageFeed = useCountyOutages(observedTime, county === "outages");
  const outNow = useMemo(() => outagesByCounty(outageFeed.data), [outageFeed.data]);
  const surgeAsOf = surgeReport.data?.as_of ?? null;
  const surgeRange = useMemo(() => surgeStarts(surgeList, surgeAsOf), [surgeList, surgeAsOf]);

  const queue = useQueue();
  const cards = useMemo(() => queue.items.flatMap((i) => (i.card ? [i.card] : [])), [queue.items]);
  const selectedCard = cards.find((c) => c.proposal_id === selectedProposalId);
  const assetList = useMemo(() => assets.data ?? [], [assets.data]);
  const sequenceKey = JSON.stringify(
    sequenceOf(selectedProposalId, queue.items, now ?? new Date().toISOString()),
  );
  const sequence = useMemo(() => JSON.parse(sequenceKey) as SequenceStep[], [sequenceKey]);
  const selectedIds = useMemo(
    () => selectedAssetIds ?? new Set(selectedCard ? placeIdsOf(selectedCard) : []),
    [selectedCard, selectedAssetIds],
  );
  const stops = useMemo<StepStop[]>(() => {
    const byId = new Map(assetList.map((a) => [a.asset_id, a]));
    return buildStops(sequence, cards, assetList).flatMap((s) => {
      const a = byId.get(s.assetId);
      return a ? [{ ...s, position: assetPosition(a) }] : [];
    });
  }, [assetList, cards, sequence]);

  const unplaced = useMemo(() => unplacedSteps(sequence, stops), [sequence, stops]);

  const values = useMemo(() => {
    const m = new Map<string, CountyValue>();
    for (const r of risk.data?.items ?? [])
      m.set(r.entity_id, { fips: r.entity_id, name: "", risk: r.p_ppm });
    for (const [fips, gust] of Object.entries(hazard.data?.county_peak_gust_ms ?? {})) {
      m.set(fips, { ...(m.get(fips) ?? { fips, name: "" }), gust });
    }
    for (const [fips, out] of outNow) m.set(fips, { ...(m.get(fips) ?? { fips, name: "" }), out });
    return m;
  }, [risk.data, hazard.data, outNow]);
  const domain = useMemo(() => {
    const list = [...values.values()];
    return county === "risk"
      ? domainOf(list.map((v) => v.risk))
      : county === "wind"
        ? domainOf(list.map((v) => v.gust))
        : county === "outages"
          ? domainOf(list.map((v) => v.out))
          : null;
  }, [values, county]);
  const product = hazard.data ? products.data?.[issuedKey(hazard.data.issued_utc)] : undefined;
  const storm = useMemo(() => stormGeometry(hazard.data, product), [hazard.data, product]);

  return {
    assets,
    assetList,
    advisories,
    issued,
    current,
    label,
    hazard,
    basemap: basemap.data,
    cards,
    selectedCard,
    sequence,
    stops,
    unplaced,
    selectedIds,
    values,
    domain,
    storm,
    now,
    observedTime,
    observations: observations.data,
    observationsFailed: observations.isError,
    surges: surgeList,
    surgeAsOf,
    surgeRange,
    surgesFailed: surgeReport.isError,
    outagesReported: Boolean(outageFeed.data?.as_of),
    outagesFailed: outageFeed.isError,
    failed: assets.isError || hazard.isError,
    noForecast: risk.isError || (risk.isSuccess && (risk.data?.items.length ?? 0) === 0),
  };
}
