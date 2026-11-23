import { Check, ChevronRight, LoaderCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { toolVerb } from "../agent-panel/labels";
import { elapsedMs, formatElapsed } from "../agent-panel/runFormat";
import { plainToolArg } from "../agent-panel/ToolChip";
import type { RunView, ToolStatus } from "../agent-panel/types";

const NOUN: Record<string, readonly [string, string]> = {
  get_decision_case: ["decision", "decisions"],
  get_water_status: ["water status check", "water status checks"],
  get_forecast: ["forecast", "forecasts"],
  search_procedures: ["procedure search", "procedure searches"],
  get_risk: ["risk read", "risk reads"],
  get_outages: ["outage read", "outage reads"],
  get_crews: ["crew read", "crew reads"],
  list_anomalies: ["sensor check", "sensor checks"],
  get_feed_health: ["feed check", "feed checks"],
  run_what_if: ["what-if", "what-ifs"],
  list_decisions: ["decision queue read", "decision queue reads"],
  get_readiness: ["readiness read", "readiness reads"],
  get_etr: ["restoration estimate", "restoration estimates"],
  list_outage_surges: ["surge check", "surge checks"],
  get_damage_photos: ["photo read", "photo reads"],
};

export type Lang = "en" | "pl";

/** Polish nouns with their three counted forms: 1, 2-4 (not 12-14), the rest. */
const NOUN_PL: Record<string, readonly [string, string, string]> = {
  get_decision_case: ["decyzja", "decyzje", "decyzji"],
  get_water_status: ["sprawdzenie stanu wody", "sprawdzenia stanu wody", "sprawdzeń stanu wody"],
  get_forecast: ["prognoza", "prognozy", "prognoz"],
  search_procedures: ["wyszukiwanie w procedurach", "wyszukiwania w procedurach", "wyszukiwań w procedurach"],
  get_risk: ["odczyt ryzyka", "odczyty ryzyka", "odczytów ryzyka"],
  get_outages: ["odczyt awarii", "odczyty awarii", "odczytów awarii"],
  get_crews: ["odczyt brygad", "odczyty brygad", "odczytów brygad"],
  list_anomalies: ["sprawdzenie czujników", "sprawdzenia czujników", "sprawdzeń czujników"],
  get_feed_health: ["sprawdzenie źródeł danych", "sprawdzenia źródeł danych", "sprawdzeń źródeł danych"],
  run_what_if: ["scenariusz co-jeśli", "scenariusze co-jeśli", "scenariuszy co-jeśli"],
  list_decisions: ["odczyt kolejki decyzji", "odczyty kolejki decyzji", "odczytów kolejki decyzji"],
  get_readiness: ["odczyt gotowości", "odczyty gotowości", "odczytów gotowości"],
  get_etr: ["szacunek czasu przywrócenia", "szacunki czasu przywrócenia", "szacunków czasu przywrócenia"],
  list_outage_surges: ["sprawdzenie skoków awarii", "sprawdzenia skoków awarii", "sprawdzeń skoków awarii"],
  get_damage_photos: ["odczyt zdjęć", "odczyty zdjęć", "odczytów zdjęć"],
};

/** The Polish form for a count: 1, 2-4 (except 12-14), everything else. */
export const plForm = (n: number): 0 | 1 | 2 =>
  n === 1 ? 0 : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 1 : 2;

function stepsSummaryPl(counts: Map<string, number>, ms: number | null): string {
  const parts = [...counts].map(([tool, n]) => `${n} ${NOUN_PL[tool]?.[plForm(n)] ?? tool}`);
  const what =
    parts.length === 0
      ? "pytanie"
      : parts.length === 1
        ? parts[0]
        : `${parts.slice(0, -1).join(", ")} i ${parts[parts.length - 1]}`;
  return `Sprawdzono: ${what}${ms === null ? "" : ` (${formatElapsed(ms)})`}`;
}

export function stepsSummary(run: RunView, lang: Lang = "en"): string {
  const counts = new Map<string, number>();
  for (const t of run.tools) if (t.status === "ok") counts.set(t.tool, (counts.get(t.tool) ?? 0) + 1);
  if (lang === "pl") return stepsSummaryPl(counts, elapsedMs(run));
  const parts = [...counts].map(([tool, n]) => {
    const noun = NOUN[tool] ?? [tool, tool];
    return `${n} ${n === 1 ? noun[0] : noun[1]}`;
  });
  const what =
    parts.length === 0
      ? "the question"
      : parts.length === 1
        ? parts[0]
        : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  const ms = elapsedMs(run);
  return `Checked ${what}${ms === null ? "" : ` in ${formatElapsed(ms)}`}`;
}

/** What a lookup is doing while it runs, in plain words. */
const LIVE_TOOL: Record<string, string> = {
  get_decision_case: "Reading the decision",
  get_water_status: "Checking pump stations and tanks",
  get_forecast: "Reading the forecast",
  search_procedures: "Searching the procedures",
  get_risk: "Checking outage risk",
  get_outages: "Reading outages",
  get_crews: "Checking crews",
  list_anomalies: "Checking water sensors",
  get_feed_health: "Checking the data feeds",
  run_what_if: "Running a what-if",
  list_decisions: "Reading the decision queue",
  get_readiness: "Checking readiness",
  get_etr: "Reading restoration times",
  list_outage_surges: "Checking outage surges",
  get_damage_photos: "Looking at damage photos",
  get_model_card: "Reading how the model works",
};

/** What a graph step is doing while it runs; steps that take no time are not named. */
const LIVE_NODE: Record<string, string> = {
  route_intent: "Reading the question",
  investigate: "Looking things up",
  guide: "Finding the right place on the platform",
  plan: "Choosing what to check",
  gather: "Collecting the findings",
  synthesise: "Writing the answer",
  link: "Checking the answer against its sources",
  respond: "Checking the answer against its sources",
};

const WORKER: Record<string, string> = {
  forecast: "Checking the forecast",
  grid: "Checking the grid",
  water: "Checking water service",
  policy: "Checking procedures and decisions",
  data_quality: "Checking the data feeds",
};

/** The live line for a Polish question: one plain phrase per kind of step. */
const LIVE_PL = {
  question: "Czytam pytanie…",
  lookup: "Sprawdzam dane…",
  plan: "Wybieram, co sprawdzić…",
  write: "Piszę odpowiedź…",
  check: "Sprawdzam odpowiedź ze źródłami…",
} as const;

function liveStepPl(run: RunView): string {
  if (run.tools.some((t) => t.status === "running")) return LIVE_PL.lookup;
  const node = [...run.nodes].reverse().find((n) => n.status === "running")?.node ?? "";
  if (node === "plan") return LIVE_PL.plan;
  if (node === "synthesise" || node === "guide") return LIVE_PL.write;
  if (node === "link" || node === "respond") return LIVE_PL.check;
  if (node === "route_intent" || (!node && run.tools.length === 0)) return LIVE_PL.question;
  return LIVE_PL.lookup;
}

/** What the run is doing now, from its own events: the running lookup, else the newest running step. */
export function liveStep(run: RunView, lang: Lang = "en"): string {
  if (lang === "pl") return liveStepPl(run);
  const tool = [...run.tools].reverse().find((t) => t.status === "running");
  if (tool) return `${LIVE_TOOL[tool.tool] ?? toolVerb(tool.tool)}…`;
  for (const n of [...run.nodes].reverse()) {
    if (n.status !== "running") continue;
    const [kind, name] = n.node.split(":");
    if (kind === "worker" && name && WORKER[name]) return `${WORKER[name]}…`;
    if (LIVE_NODE[n.node]) return `${LIVE_NODE[n.node]}…`;
  }
  return run.tools.length > 0 ? "Looking things up…" : "Reading the question…";
}

interface Lookup {
  key: string;
  verb: string;
  arg: string;
  count: number;
  status: ToolStatus;
}

/** The same lookup made several times reads once with its count. */
function groupedLookups(run: RunView): Lookup[] {
  const groups = new Map<string, Lookup>();
  for (const t of run.tools) {
    const verb = toolVerb(t.tool);
    const arg = plainToolArg(t.args);
    const key = `${verb}|${arg}`;
    const seen = groups.get(key);
    if (seen) seen.count += 1;
    else groups.set(key, { key, verb, arg, count: 1, status: t.status });
  }
  return [...groups.values()];
}

const ICON = { running: LoaderCircle, ok: Check, refused: X, error: X } as const;

/**
 * One folded line: while the run works it names the current step ("Reading the decision…"), then
 * "Checked 3 decisions and 1 procedure search in 41 s". It opens to the steps in plain words.
 */
export function StepsLine({
  run,
  onDetails,
  lang = "en",
}: {
  run: RunView;
  onDetails: () => void;
  lang?: Lang;
}) {
  const working = run.status === "running" && run.answer === null;
  const summary = working ? liveStep(run, lang) : stepsSummary(run, lang);
  const answered = run.answer !== null;
  const Lead = working ? LoaderCircle : Check;
  return (
    <Collapsible className="group/steps" data-testid="steps">
      <CollapsibleTrigger
        aria-label={`Show steps. ${summary}`}
        className="inline-flex min-h-7 items-center gap-1.5 text-[13px] font-medium text-muted hover:text-ink"
      >
        <Lead aria-hidden className={working ? "size-4 animate-spin text-muted" : "size-4 text-ink-2"} />
        <span data-testid="steps-summary">{summary}</span>
        <ChevronRight
          aria-hidden
          className="size-3.5 transition-transform duration-160 group-data-[state=open]/steps:rotate-90"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0 pl-[22px] text-[13px]" aria-label="Steps">
          <li className="text-ink-2">Read the question</li>
          {groupedLookups(run).map((g) => {
            const Icon = ICON[g.status];
            return (
              <li key={g.key} className="flex items-center gap-1.5 text-ink-2">
                <Icon aria-hidden className="size-3 shrink-0 text-muted" />
                <span className="shrink-0">
                  {g.verb}
                  {g.count > 1 && ` (${g.count})`}
                </span>
                {g.arg && <span className="min-w-0 truncate text-[12px] text-muted">{g.arg}</span>}
              </li>
            );
          })}
          {answered && <li className="text-ink-2">Checked the answer against its sources</li>}
          <li className="pt-1">
            <Button variant="tertiary" size="sm" className="h-6 px-0" onClick={onDetails}>
              Step details
            </Button>
          </li>
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
