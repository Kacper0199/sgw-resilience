import { parseAsString, parseAsStringLiteral, useQueryState, useQueryStates } from "nuqs";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { VIEWS } from "./hazardModel";

const TABS = [
  { value: "pre-season", label: "Pre-season" },
  { value: "heat", label: "Heat wave" },
  { value: "wildfire", label: "Wildfire weather" },
] as const;

export const useReadinessView = () => useQueryState("view", parseAsStringLiteral(VIEWS));

/** Pre-season checks and the hazard library, one tab row under the Readiness header; `?view=` deep-links a hazard. */
export function ReadinessTabs() {
  const [view] = useReadinessView();
  const [, setParams] = useQueryStates({
    view: parseAsStringLiteral(VIEWS),
    item: parseAsString,
    check: parseAsString,
    domain: parseAsString,
  });
  return (
    <Tabs
      value={view ?? "pre-season"}
      onValueChange={(v) =>
        void setParams({
          view: v === "heat" || v === "wildfire" ? v : null,
          item: null,
          check: null,
          domain: null,
        })
      }
    >
      <TabsList aria-label="Readiness views" className="px-8" data-testid="readiness-tabs">
        {TABS.map((t) => (
          <TabsTrigger key={t.value} value={t.value} aria-controls={undefined}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
