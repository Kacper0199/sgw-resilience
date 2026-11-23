import { parseAsStringLiteral, useQueryState } from "nuqs";
import { CountBadge, type KeyNumber, KeyNumberStrip, PageHeader } from "@/components/sgw";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { loadFailureLine } from "@/lib/loadFailure";
import { isPack } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import { SensorContainer } from "../water/SensorContainer";
import { DataTab } from "./DataTab";
import { ageText, feedName, feedStatus, humanize, list } from "./format";
import { ModelsTab } from "./ModelsTab";
import { specFor } from "./modelFacts";
import { RunsTab } from "./RunsTab";
import { SafetyTab } from "./SafetyTab";
import { KILL_LEVELS } from "./safety";
import { useCapabilities, useFeeds, useModels } from "./useHealth";

const TABS = ["data", "models", "sensors", "runs", "safety"] as const;
const TAB_LABEL = {
  data: "Data",
  models: "Models",
  sensors: "Sensor checks",
  runs: "AI activity",
  safety: "Stop controls",
} as const;

const ofTotal = (n: number, total: number) => (
  <>
    {n} <span className="text-[14px] font-normal text-muted">of {total}</span>
  </>
);

const modelNames = (names: string[]) =>
  names.length <= 1 ? list(names) : `${names[0]} and ${names.length - 1} more`;

export default function HealthPage() {
  const [tab, setTab] = useQueryState("tab", parseAsStringLiteral(TABS).withDefault("data"));
  const feeds = useFeeds();
  const models = useModels();
  const caps = useCapabilities();
  const scripted = isPack(useScenario().data?.scenario);

  const late = scripted ? [] : (feeds.data ?? []).filter((f) => feedStatus(f) === "late");
  const onTime = (feeds.data ?? []).filter((f) => feedStatus(f) === "on_time");
  const noData = (feeds.data ?? []).filter((f) => feedStatus(f) === "no_data");
  const quiet = (feeds.data ?? []).filter((f) => feedStatus(f) === "quiet");
  const first = late[0];
  const state = caps.data;
  const exercise: KeyNumber[] = [
    { label: "Data on time", value: "–", line: "Scripted exercise data", info: "feed_freshness" },
    { label: "Late data", value: "–", line: "No live feeds in this exercise" },
  ];
  const items: KeyNumber[] = [
    {
      label: "Data on time",
      value: feeds.data ? ofTotal(onTime.length, feeds.data.length - quiet.length) : "–",
      line: feeds.error
        ? loadFailureLine(feeds.error)
        : noData.length > 0
          ? `${noData.length} with no data yet`
          : quiet.length > 0
            ? `${quiet.length} with no changes to report yet`
            : "Sources within their max age",
      info: "feed_freshness",
    },
    {
      label: "Late data",
      value: feeds.data ? late.length : "–",
      tone: late.length > 0 ? "warn" : undefined,
      line: first
        ? `${feedName(first)}, ${ageText(first.product_age_s)} (max ${ageText(first.freshness_limit_s)})${late.length > 1 ? ` and ${late.length - 1} more` : ""}`
        : feeds.data
          ? "Nothing is late"
          : feeds.error
            ? loadFailureLine(feeds.error)
            : undefined,
    },
    {
      label: "Models in use",
      value: models.data ? models.data.length : "–",
      line: models.data
        ? modelNames(models.data.map((m) => specFor(m.name)?.title ?? humanize(m.name)))
        : models.error
          ? loadFailureLine(models.error)
          : undefined,
    },
    {
      label: "SGW mode",
      value: state
        ? (state.mode_ladder.find((m) => m.mode === state.degraded_mode)?.name ?? state.degraded_mode)
        : "–",
      tone: state && (state.degraded_mode !== "M0" || state.kill_level !== "K0") ? "warn" : undefined,
      line: state
        ? state.kill_level === "K0"
          ? "Nothing is stopped"
          : KILL_LEVELS[state.kill_level].label
        : caps.error
          ? loadFailureLine(caps.error)
          : undefined,
    },
  ];

  return (
    <div className="min-h-full">
      <PageHeader title="System health" info="feed_freshness" />
      <KeyNumberStrip items={scripted ? [...exercise, ...items.slice(2)] : items} />
      <Tabs value={tab} onValueChange={(v) => void setTab(v as (typeof TABS)[number])}>
        <TabsList aria-label="System health sections" className="px-8">
          {TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {TAB_LABEL[t]}
              {t === "data" && late.length > 0 && <CountBadge count={late.length} tone="warn" />}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="data" className="pt-0">
          <DataTab />
        </TabsContent>
        <TabsContent value="models" className="pt-0 pb-8">
          <ModelsTab />
        </TabsContent>
        <TabsContent value="sensors" className="pt-0 pb-8">
          <SensorContainer />
        </TabsContent>
        <TabsContent value="runs" className="pt-0 pb-8">
          <RunsTab />
        </TabsContent>
        <TabsContent value="safety" className="pt-0 pb-8">
          <SafetyTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
