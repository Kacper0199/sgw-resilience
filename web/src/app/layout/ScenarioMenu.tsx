import { ChevronDown, Info, LoaderCircle, Pause, Play } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { useMe } from "@/auth/useSession";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DATA_SOURCES, PACK_DATA_SOURCES } from "@/content/dataSources";
import { ApiError, type ScenarioState } from "@/lib/api";
import { isPack } from "@/lib/scenarios";
import { formatDayET, formatET } from "@/lib/time";
import { useScenario, useScenarioNow } from "@/sse/useScenarioNow";
import {
  canMoveClock,
  directionOf,
  type LoadableScenario,
  type ReplaySpeed,
  useLoadMoment,
  useLoadScenario,
  useReplayCommand,
  useScenarioJump,
} from "./scenarioJump";

type Moment = ScenarioState["jumps"] extends (infer M)[] | undefined ? M : never;

const MODE_LABEL = { REPLAY: "Replay", EXERCISE: "Exercise" } as const;
const SPEEDS: readonly ReplaySpeed[] = [1, 60, 900];
const when = (iso: string) => `${formatDayET(iso)}, ${formatET(iso)}`;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-hair px-4 py-2.5 first:border-t-0">
      <h3 className="m-0 mb-1 text-[12px] font-semibold text-muted">{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex items-baseline justify-between gap-3 text-[13px] leading-[22px]">
      <span className="min-w-0 truncate">{label}</span>
      <span className="shrink-0 text-muted tnum">{value}</span>
    </li>
  );
}

const OTHER_SCENARIOS = [
  { view: "heat", label: "Heat wave, July 2024" },
  { view: "wildfire", label: "Wildfire weather, March 2025" },
] as const;

const LOADABLE: Record<LoadableScenario, { label: string; title: string }> = {
  helene: { label: "Hurricane Helene, September 2024", title: "Hurricane Helene" },
  ian: { label: "Hurricane Ian, September 2022", title: "Hurricane Ian" },
};

/** Another storm to load (presenters with Load moment), then the read-only hazard views in Readiness. */
function OtherScenarios({
  active,
  canLoad,
  onOpen,
  onLoad,
}: {
  active: string;
  canLoad: boolean;
  onOpen: () => void;
  onLoad: (scenario: LoadableScenario) => void;
}) {
  const loadable = canLoad ? (Object.keys(LOADABLE) as LoadableScenario[]).filter((s) => s !== active) : [];
  return (
    <Section title="Other scenarios">
      <ul className="-mx-2 m-0 list-none p-0" data-testid="other-scenarios" aria-label="Other scenarios">
        {loadable.map((s) => (
          <li key={s}>
            <button
              type="button"
              onClick={() => onLoad(s)}
              className="flex w-full items-baseline justify-between gap-3 rounded-md px-2 py-1 text-left text-[13px] hover:bg-surface-2"
            >
              <span className="min-w-0 truncate font-medium">{LOADABLE[s].label}</span>
              <span className="shrink-0 font-semibold text-blue-ink">Load</span>
            </button>
          </li>
        ))}
        {OTHER_SCENARIOS.map((s) => (
          <li key={s.view}>
            <Link
              to={`/readiness?view=${s.view}`}
              onClick={onOpen}
              className="flex items-baseline justify-between gap-3 rounded-md px-2 py-1 text-[13px] hover:bg-surface-2"
            >
              <span className="min-w-0 truncate font-medium">{s.label}</span>
              <span className="shrink-0 text-muted">Readiness preview</span>
            </Link>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function LoadScenarioDialog({ target, onClose }: { target: LoadableScenario | null; onClose: () => void }) {
  const load = useLoadScenario();
  const busy = load.isPending;
  const failed = load.error;
  const problem = failed instanceof ApiError ? failed.message : failed ? "The server did not answer." : null;
  const close = () => {
    if (busy) return;
    load.reset();
    onClose();
  };
  const confirm = () => {
    if (!target) return;
    load.mutate(target, {
      onSuccess: () => {
        toast.success(`Loaded ${LOADABLE[target].title}.`);
        load.reset();
        onClose();
      },
      onError: () => toast.error("Couldn't load the scenario. Nothing changed."),
    });
  };
  const pack = target === "ian";
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent data-testid="load-scenario-dialog">
        <DialogTitle>Load {target ? LOADABLE[target].title : ""}?</DialogTitle>
        <DialogDescription>
          {pack
            ? "Everyone using this demo switches to the Hurricane Ian exercise, a day before landfall. Its outages, decisions and crews are scripted."
            : "Everyone using this demo returns to the Helene replay at the 11 AM advisory, with its saved decisions."}
        </DialogDescription>
        {problem && (
          <p role="alert" className="m-0 text-[13px] font-medium text-crit">
            Couldn't load: {problem}
          </p>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={confirm} disabled={busy} data-autofocus>
            {busy && <LoaderCircle className="motion-safe:animate-spin" aria-hidden />}
            {busy ? "Loading…" : "Load scenario"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function KeyMoments({ moments }: { moments: Moment[] }) {
  const advisories = moments.filter((m) => m.kind === "advisory");
  const first = advisories[0];
  const last = advisories.at(-1);
  const others = moments.filter((m) => m.kind !== "advisory");
  return (
    <ul className="m-0 list-none p-0" data-testid="key-moments">
      {first && last && (
        <Row
          label={`${advisories.length} hurricane advisories`}
          value={`${formatDayET(first.scenario_time)} – ${formatDayET(last.scenario_time)}`}
        />
      )}
      {others.map((m) => (
        <Row key={m.moment_id} label={m.label} value={when(m.scenario_time)} />
      ))}
    </ul>
  );
}

function ReplayControls({ speed }: { speed: number }) {
  const command = useReplayCommand();
  const running = speed > 0;
  const send = (cmd: Parameters<typeof command.mutate>[0]) =>
    command.mutate(cmd, { onError: () => toast.error("Couldn't change the replay clock.") });
  return (
    <div className="mb-1.5 flex items-center gap-2" data-testid="replay-controls">
      <Button
        size="sm"
        variant="secondary"
        disabled={command.isPending}
        onClick={() => send(running ? { action: "pause" } : { action: "play" })}
      >
        {running ? <Pause aria-hidden /> : <Play aria-hidden />}
        {running ? "Pause" : "Play"}
      </Button>
      <fieldset aria-label="Replay speed" className="m-0 inline-flex rounded-[7px] border border-line p-0">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={speed === s}
            disabled={command.isPending}
            onClick={() => send({ action: "speed", speed: s })}
            className="h-7 px-2.5 text-[12px] tnum first:rounded-l-[6px] last:rounded-r-[6px] hover:bg-surface-2 aria-pressed:bg-surface-2 aria-pressed:font-semibold"
          >
            {s}×
          </button>
        ))}
      </fieldset>
    </div>
  );
}

function JumpDialog({
  target,
  canLoad,
  scripted,
  onClose,
}: {
  target: Moment | null;
  canLoad: boolean;
  scripted: boolean;
  onClose: () => void;
}) {
  const jump = useScenarioJump();
  const load = useLoadMoment();
  const now = useScenarioNow();
  const back = target ? directionOf(target.scenario_time, now) === "back" : false;
  const busy = jump.isPending || load.isPending;
  const failed = jump.error ?? load.error;
  const at = target ? when(target.scenario_time) : "";
  const clockMoves = scripted
    ? `The exercise clock moves to ${at} for everyone in this exercise.`
    : `The replay clock moves to ${at} for everyone using this replay.`;
  const problem = failed instanceof ApiError ? failed.message : failed ? "The server did not answer." : null;
  const close = () => {
    if (busy) return;
    jump.reset();
    load.reset();
    onClose();
  };
  const loadMoment = () => {
    if (!target) return;
    load.mutate(target.moment_id, {
      onSuccess: () => {
        toast.success(`Loaded ${target.label}.`);
        load.reset();
        onClose();
      },
      onError: () => toast.error("Couldn't load the moment. Nothing changed."),
    });
  };
  const confirm = () => {
    if (!target) return;
    jump.mutate(target.scenario_time, {
      onSuccess: () => {
        toast.success(`${scripted ? "Exercise clock" : "Replay"} moved to ${when(target.scenario_time)}.`);
        jump.reset();
        onClose();
      },
      onError: () =>
        toast.error(`Couldn't move the ${scripted ? "exercise clock" : "replay"}. Nothing changed.`),
    });
  };
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent data-testid="jump-dialog">
        <DialogTitle>
          {canLoad ? "Go to" : "Jump to"} {target?.label}?
        </DialogTitle>
        <DialogDescription>
          {canLoad
            ? `Load moment sets decisions, crews and water to their saved state at ${target ? when(target.scenario_time) : ""}.`
            : clockMoves}
        </DialogDescription>
        <details className="group text-[13px] text-ink-2">
          <summary className="inline-flex cursor-pointer items-center gap-1 font-semibold text-blue-ink select-none hover:underline">
            <Info className="size-3.5" aria-hidden />
            Info
          </summary>
          <ul className="m-0 mt-1.5 flex list-disc flex-col gap-1 pl-5 text-[13px]">
            <li>{clockMoves}</li>
            <li>Open decisions whose deadline moves are revised, and their signatures are voided.</li>
            <li>Decisions past their expiry expire.</li>
            {back && <li>Going back does not undo decisions already recorded.</li>}
            {canLoad && (
              <li>
                Load moment replaces all decisions with the moment's saved state; jumping the clock only keeps
                them.
              </li>
            )}
          </ul>
        </details>
        {problem && (
          <p role="alert" className="m-0 text-[13px] font-medium text-crit">
            Couldn't jump: {problem}
          </p>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant={canLoad ? "secondary" : "primary"}
            onClick={confirm}
            disabled={busy}
            data-autofocus={canLoad ? undefined : true}
          >
            {jump.isPending && <LoaderCircle className="motion-safe:animate-spin" aria-hidden />}
            {jump.isPending ? "Jumping…" : canLoad ? "Jump clock only" : "Jump"}
          </Button>
          {canLoad && (
            <Button variant="primary" onClick={loadMoment} disabled={busy} data-autofocus>
              {load.isPending && <LoaderCircle className="motion-safe:animate-spin" aria-hidden />}
              {load.isPending ? "Loading…" : "Load moment"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The one scenario control in the top band: what is replayed, when, from which data, and for presenters where to jump. */
export function ScenarioMenu() {
  const { data } = useScenario();
  const me = useMe();
  const now = useScenarioNow();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<Moment | null>(null);
  const [loadTarget, setLoadTarget] = useState<LoadableScenario | null>(null);
  if (!data) return <div className="h-7 w-80 rounded bg-topbar-field" aria-hidden />;
  const period = data.period;
  const title = period?.title ?? data.scenario;
  const operator = canMoveClock(me.data);
  const jumps = operator ? (data.jumps ?? []) : [];
  const scripted = isPack(data.scenario);
  const mode = scripted ? "Exercise" : MODE_LABEL[data.mode];
  const sources = scripted ? PACK_DATA_SOURCES : DATA_SOURCES;
  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="inline-flex h-7 max-w-full min-w-0 items-center gap-2 rounded-md border border-topbar-line pr-1.5 pl-2.5 text-[12px] whitespace-nowrap hover:bg-topbar-hover"
            data-testid="mode-strip"
          >
            <span
              aria-hidden
              className="size-[7px] shrink-0 rounded-full border-[1.5px] border-topbar-muted"
            />
            <span className="min-w-0 truncate">
              {mode} of <span className="max-[1499px]:hidden">{title}</span>
              <span className="min-[1500px]:hidden">{title.replace("Hurricane ", "")}</span>
              {period && `, ${period.label}`}, {scripted ? "scripted " : ""}synthetic{" "}
              <span className="max-[1499px]:hidden">SGW </span>
              data
            </span>
            <ChevronDown className="size-3.5 shrink-0 text-topbar-muted" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="max-h-[calc(100dvh-72px)] w-[380px] overflow-y-auto p-0"
          data-testid="scenario-menu"
        >
          <Section title="Scenario">
            <p className="m-0 text-[14px] font-semibold">
              {title} {mode.toLowerCase()}
            </p>
            {period && (
              <p className="m-0 text-[13px] text-ink-2" data-testid="scenario-period">
                {period.label}, Eastern time
              </p>
            )}
            <p className="m-0 mt-1 text-[12px] text-muted">{period?.data_note ?? "Synthetic SGW data"}</p>
          </Section>
          <OtherScenarios
            active={data.scenario}
            canLoad={operator && Boolean(data.loads_moments)}
            onOpen={() => setOpen(false)}
            onLoad={(s) => {
              setOpen(false);
              setLoadTarget(s);
            }}
          />
          {!operator && (data.moments ?? []).length > 0 && (
            <Section title="Key moments">
              <KeyMoments moments={data.moments ?? []} />
            </Section>
          )}
          <Section title="Data sources">
            {!operator && (
              <ul className="m-0 list-none p-0" data-testid="data-sources">
                {sources.map((s) => (
                  <Row key={s.key} label={s.what} value={s.real ? "Real" : "Synthetic"} />
                ))}
              </ul>
            )}
            <Link
              to="/help#data-sources"
              onClick={() => setOpen(false)}
              className="mt-1 inline-block text-[13px] font-semibold text-blue-ink hover:underline"
            >
              Sources and licences
            </Link>
          </Section>
          {operator && (
            <Section title={scripted ? "Exercise clock" : "Replay"}>
              <ReplayControls speed={data.speed} />
              <ul className="-mx-2 m-0 list-none p-0" data-testid="jump-list">
                {jumps.map((j) => {
                  const here = directionOf(j.scenario_time, now) === "here";
                  return (
                    <li key={j.moment_id}>
                      <button
                        type="button"
                        disabled={here}
                        onClick={() => {
                          setOpen(false);
                          setTarget(j);
                        }}
                        className="flex w-full items-baseline justify-between gap-3 rounded-md px-2 py-1 text-left text-[13px] hover:bg-surface-2 disabled:cursor-default disabled:text-muted disabled:hover:bg-transparent"
                      >
                        <span className="min-w-0 truncate font-medium">{j.label}</span>
                        <span className="shrink-0 text-muted tnum">
                          {here ? "Now" : when(j.scenario_time)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Section>
          )}
        </PopoverContent>
      </Popover>
      <JumpDialog
        target={target}
        canLoad={Boolean(data.loads_moments) && !scripted}
        scripted={scripted}
        onClose={() => setTarget(null)}
      />
      <LoadScenarioDialog target={loadTarget} onClose={() => setLoadTarget(null)} />
    </>
  );
}
