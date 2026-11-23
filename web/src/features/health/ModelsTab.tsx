import { Brain } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, InfoTip, Section } from "@/components/sgw";
import { aiStepName } from "@/lib/aiSteps";
import { ReasonTip } from "../decisions/ReasonTip";
import { Failed, Loading } from "./Async";
import { withEdges } from "./edge";
import { humanize, list, modelName, PLATFORM_CLOCK, platformTime, plural, shortHash } from "./format";
import { type Fact, factsFor, reportDate, reportName, reportRows, specFor } from "./modelFacts";
import { SectionHead } from "./SectionHead";
import { Mark, StatusLine } from "./Status";
import type { AiNodeConfig, ModelCard as ModelCardData } from "./types";
import { isNotShown, useAiConfig, useEvaluations, useModels } from "./useHealth";

function FactList({ facts }: { facts: Fact[] }) {
  return (
    <dl className="m-0 mt-3 grid">
      {facts.map((f) => (
        <div
          key={f.label}
          className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 border-t border-hair py-2.5"
          data-testid="model-fact"
        >
          <dt className="min-w-0 text-[13px] text-muted">{f.label}</dt>
          <dd className="m-0 flex items-baseline gap-3 text-right">
            <span className="text-[14px] font-semibold tnum">{f.value}</span>
            {f.mark && (
              <Mark tone={f.mark === "met" ? "ok" : "warn"}>{f.mark === "met" ? "Met" : "Below target"}</Mark>
            )}
          </dd>
          {f.target && <dd className="col-span-2 m-0 text-right text-[12px] text-muted">{f.target}</dd>}
        </div>
      ))}
    </dl>
  );
}

export function ModelCard({
  card,
  evaluation,
  loading,
}: {
  card: ModelCardData;
  evaluation: Parameters<typeof reportRows>[0];
  loading: boolean;
}) {
  const spec = specFor(card.name);
  const rows = reportRows(evaluation);
  const facts = factsFor(spec, rows);
  const dated = reportDate(evaluation);
  return (
    <Section
      title={
        <>
          {spec?.title ?? humanize(card.name)}
          {spec?.wording?.length ? (
            <ReasonTip label="About this model" title="About this model">
              {spec.wording.map((w) => (
                <p key={w} className="m-0">
                  {w}
                </p>
              ))}
            </ReasonTip>
          ) : (
            <InfoTip term="model_card" />
          )}
        </>
      }
    >
      {spec?.does && <p className="m-0 mt-2 text-[14px]">{spec.does}</p>}
      {loading ? (
        <p role="status" className="m-0 mt-3 text-[13px] text-muted">
          Loading results…
        </p>
      ) : facts.length > 0 ? (
        <FactList facts={facts} />
      ) : (
        <p className="m-0 mt-3 border-t border-hair pt-2.5 text-[13px] text-muted">No test results yet.</p>
      )}
      {dated && (
        <p
          className="m-0 mt-2 text-[12px] text-muted"
          title={`${card.name} version ${card.version}, data ${shortHash(card.data_hash)}, report ${reportName(evaluation) ?? card.eval_report ?? "unknown"}. ${PLATFORM_CLOCK}`}
        >
          Model tested on {platformTime(dated)} (build date)
        </p>
      )}
    </Section>
  );
}

function Summary({ cards, below }: { cards: ModelCardData[] | undefined; below: string[] }) {
  if (!cards)
    return <StatusLine tone="idle" headline="Loading model results…" detail="Model details are loading." />;
  if (cards.length === 0) return <StatusLine tone="idle" headline="No models yet." />;
  if (below.length === 0)
    return (
      <StatusLine
        tone="ok"
        headline={`${plural(cards.length, "model")} in use.`}
        detail="All results meet their targets."
      />
    );
  return (
    <StatusLine
      tone="warn"
      headline={`${plural(cards.length, "model")} in use; ${below.length} below target.`}
      detail={`${list(below)}. Details below.`}
    />
  );
}

const nodeColumns: DataColumn<AiNodeConfig>[] = [
  {
    id: "step",
    header: "Step",
    cell: (n) => <span className="font-medium">{aiStepName(n.node)}</span>,
  },
  {
    id: "model",
    header: "Model",
    cell: (n) => <span className="font-medium">{modelName(n.model)}</span>,
  },
  { id: "effort", header: "Effort", cell: (n) => humanize(n.effort) },
  { id: "class", header: "Data allowed", cell: (n) => `Up to ${n.class_ceiling}` },
  { id: "cites", header: "Cites sources", cell: (n) => (n.citations ? "Yes" : "No") },
  {
    id: "check",
    header: "Latest check",
    cell: (n) =>
      n.eval_result ? (
        <span className="flex items-baseline gap-2">
          <span className="tnum">{Math.round(n.eval_result.value_ppm / 10_000)}%</span>
          <Mark tone={n.eval_result.passed ? "ok" : "warn"}>
            {n.eval_result.passed ? "Passed" : "Below target"}
          </Mark>
        </span>
      ) : (
        <span className="text-muted">Not tested</span>
      ),
  },
];

function AiNodes() {
  const config = useAiConfig();
  return (
    <>
      <SectionHead title="AI models by step" />
      {!config.allowed || isNotShown(config.error) ? (
        <p className="m-0 px-8 pb-6 text-[13px] text-muted" data-testid="ai-config-hidden">
          Only administrators can see which model each AI step uses.
        </p>
      ) : config.isPending ? (
        <Loading what="AI steps" />
      ) : config.error ? (
        <Failed what="AI steps" error={config.error} />
      ) : (
        <AiNodeTable nodes={config.data.nodes} />
      )}
    </>
  );
}

function AiNodeTable({ nodes }: { nodes: AiNodeConfig[] }) {
  const counts = new Map<string, number>();
  for (const n of nodes) counts.set(n.model, (counts.get(n.model) ?? 0) + 1);
  const summary = [...counts.entries()].map(([model, n]) => `${n} on ${modelName(model)}`).join(", ");
  return (
    <>
      <p className="m-0 px-8 pb-2 text-[13px] text-muted" data-testid="ai-node-summary">
        {plural(nodes.length, "step")}: {summary}. Read-only; changes go through the platform team.
      </p>
      <DataTable
        compact
        caption="AI steps"
        data={nodes}
        getRowId={(n) => n.node}
        rowTestId="ai-node-row"
        columns={withEdges(nodeColumns)}
      />
    </>
  );
}

export function ModelsTab() {
  const models = useModels();
  const names = models.data?.map((m) => m.name) ?? [];
  const evaluations = useEvaluations(names);
  const below = (models.data ?? []).flatMap((m, i) => {
    const spec = specFor(m.name);
    const facts = factsFor(spec, reportRows(evaluations[i]?.data));
    return facts.some((f) => f.mark === "below") ? [spec?.title ?? humanize(m.name)] : [];
  });
  return (
    <div>
      <Summary cards={models.data} below={below} />
      {models.isPending ? (
        <Loading what="models" />
      ) : models.error ? (
        <Failed what="Models" error={models.error} />
      ) : models.data.length === 0 ? (
        <EmptyState icon={Brain} title="No models yet." className="py-6" />
      ) : (
        <div className="grid gap-x-12 gap-y-8 px-8 pt-6 min-[1280px]:grid-cols-2">
          {models.data.map((m, i) => (
            <ModelCard
              key={m.name}
              card={m}
              evaluation={evaluations[i]?.data}
              loading={evaluations[i]?.isPending ?? false}
            />
          ))}
        </div>
      )}
      <AiNodes />
    </div>
  );
}
