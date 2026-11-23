import type { ComponentType } from "react";
import { Link } from "react-router";
import { EmptyState, PageHeader } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { isPack, PACK_PAGES, SCENARIO_PACKS } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import { GROUP_LABEL, MODULES, type ModuleDef } from "./modules";

/** Pages whose models exist for the Helene replay only: a scripted exercise shows a plain state instead. */
export const HELENE_ONLY: ReadonlySet<ModuleDef["key"]> = new Set([
  "forecast",
  "crews",
  "water",
  "after_action",
]);

/** The pages a scripted exercise does not model, by name ("Forecast and Water"). */
export function notModelledPages(): string {
  const names = MODULES.filter((m) => HELENE_ONLY.has(m.key) && !PACK_PAGES.has(m.key)).map((m) => m.label);
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : (names[0] ?? "");
}

function NotModelled({ def, title }: { def: ModuleDef; title: string }) {
  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        breadcrumb={[{ label: "SGW", to: "/" }, { label: GROUP_LABEL[def.group] }]}
        title={def.label}
      />
      <EmptyState
        icon={def.icon}
        className="py-20"
        title="Not modelled for this scenario"
        description={`${title} is a scripted exercise. ${notModelledPages()} are not modelled for it; every other page uses its data.`}
        action={
          <Button variant="tertiary" asChild>
            <Link to="/">Back to Decisions</Link>
          </Button>
        }
      />
    </div>
  );
}

/** Wraps a Helene-only page: the page itself for the replay, the plain state for a scripted exercise; nothing until the scenario is known, so a pack never sends the page's Helene requests. */
export function gated(def: ModuleDef, Page: ComponentType): ComponentType {
  function Gated() {
    const { data, isPending } = useScenario();
    if (isPending) return null;
    if (data && isPack(data.scenario))
      return <NotModelled def={def} title={SCENARIO_PACKS[data.scenario].title} />;
    return <Page />;
  }
  return Gated;
}
