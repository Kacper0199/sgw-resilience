import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { useMemo } from "react";
import { CountBadge, type KeyNumber, KeyNumberStrip, PageHeader } from "@/components/sgw";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { advisoryTime } from "@/lib/advisory";
import { loadFailureLine } from "@/lib/loadFailure";
import { usePhase } from "@/lib/PhaseProvider";
import { formatETOn } from "@/lib/time";
import { useScenarioNow } from "@/sse/useScenarioNow";
import { RestorationTab } from "../etr/RestorationTab";
import { advisoryAt, useAdvisories } from "../map/data";
import { HistoryBar } from "../map/HistoryBar";
import { affectedDecisions } from "./affected";
import { BacktestTab } from "./BacktestTab";
import { CountiesTab } from "./CountiesTab";
import { DEFAULT_REPORT, forecastPeak, useCountyForecast, usePlanDiff } from "./data";
import { count } from "./format";
import { PlanChangeTab } from "./PlanChangeTab";

const TABS = ["counties", "plan", "etr", "backtest"] as const;
const TAB_LABEL = {
  counties: "Outages",
  plan: "What changed",
  etr: "Restoration times",
  backtest: "Track record",
} as const;
const TAB_LABEL_OBSERVED = { ...TAB_LABEL, counties: "Forecast vs actual" } as const;

export default function ForecastPage() {
  const { afterPeak, advisoriesOver } = usePhase();
  const observedView = afterPeak || advisoriesOver;
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringLiteral(TABS).withDefault(afterPeak ? "etr" : "counties"),
  );
  const [at, setAt] = useQueryState("at", parseAsString);
  const [report] = useQueryState("report", parseAsString.withDefault(DEFAULT_REPORT));
  const advisories = useAdvisories();
  const now = useScenarioNow();
  const current = now === null ? null : advisoryAt(advisories.data ?? [], now);
  const issued = useMemo(
    () => (advisories.data ?? []).filter((a) => now === null || Date.parse(a.issued_utc) <= Date.parse(now)),
    [advisories.data, now],
  );
  const chosen = advisories.data?.find((a) => a.issued_utc === at)?.advisory_label;
  const label = chosen ?? current?.advisory_label ?? null;
  const forecast = useCountyForecast(label);
  const diff = usePlanDiff(label);

  const strip = useMemo<KeyNumber[]>(() => {
    const f = forecast.data;
    const d = diff.data;
    const peak = f ? forecastPeak(f.counties) : null;
    const affected = d ? affectedDecisions(d.actions) : null;
    const seen = f?.observed;
    if (observedView && seen) {
      const restored = seen.peak_customers_out > 0 ? 1 - seen.customers_out_now / seen.peak_customers_out : 0;
      return [
        {
          label: "Customers out now",
          value: count(seen.customers_out_now),
          line: "From the outage feed",
        },
        {
          label: "Peak customers out",
          value: count(seen.peak_customers_out),
          line: `${formatETOn(seen.peak_at_utc, now)}${peak === null ? "" : `, forecast peak ${count(peak)}`}`,
        },
        {
          label: "Restored since the peak",
          value: `${Math.round(restored * 100)}%`,
          line: "Of the peak customers out",
        },
      ];
    }
    return [
      {
        label: "Forecast peak, median",
        value: peak === null ? "–" : count(peak),
        line: forecast.error ? loadFailureLine(forecast.error) : "Customers out, sum of county medians",
      },
      {
        label: "Plan steps changed",
        value: affected ? (
          <>
            {affected.count} <span className="text-[13px] font-normal text-muted">of {affected.total}</span>
          </>
        ) : (
          "–"
        ),
        tone: affected?.urgent ? "warn" : undefined,
        line: affected ? (
          <>
            {`${affected.line}. `}
            <button
              type="button"
              onClick={() => void setTab("plan")}
              className="font-semibold text-blue-ink hover:underline"
            >
              See the steps
            </button>
          </>
        ) : diff.error ? (
          loadFailureLine(diff.error)
        ) : diff.isLoading ? undefined : (
          "First advisory"
        ),
      },
      {
        label: "Storm scenarios",
        value: f ? f.members : "–",
        line: f ? advisoryTime(f.issued_utc) : undefined,
      },
    ];
  }, [forecast.data, forecast.error, diff.data, diff.error, diff.isLoading, setTab, observedView, now]);

  const affectedBadge = diff.data ? affectedDecisions(diff.data.actions) : null;

  return (
    <div className="min-h-full pb-8">
      <PageHeader title="Forecast" info="fan" />
      {issued.length > 1 && (
        <div className="px-8 pb-3">
          <HistoryBar
            inline
            advisories={issued}
            label={label}
            liveLabel={current?.advisory_label ?? null}
            noForecast={!forecast.isPending && !forecast.data}
            onSelect={(next) =>
              void setAt(
                next === current?.advisory_label
                  ? null
                  : (advisories.data?.find((a) => a.advisory_label === next)?.issued_utc ?? null),
              )
            }
          />
        </div>
      )}
      <KeyNumberStrip items={strip} />
      <Tabs value={tab} onValueChange={(v) => void setTab(v as (typeof TABS)[number])}>
        <TabsList aria-label="Forecast sections" className="px-8">
          {TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {(observedView ? TAB_LABEL_OBSERVED : TAB_LABEL)[t]}
              {t === "plan" && !observedView && affectedBadge && affectedBadge.count > 0 && (
                <CountBadge count={affectedBadge.count} tone={affectedBadge.urgent ? "warn" : undefined} />
              )}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="counties" className="pt-0">
          <CountiesTab advisory={label} observed={observedView} />
        </TabsContent>
        <TabsContent value="plan" className="pt-0">
          <PlanChangeTab advisory={label} />
        </TabsContent>
        <TabsContent value="etr" className="pt-0">
          <RestorationTab />
        </TabsContent>
        <TabsContent value="backtest" className="pt-0">
          <BacktestTab report={report} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
