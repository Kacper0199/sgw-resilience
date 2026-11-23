import { type DataColumn, DataTable, InfoTip, SourceLine, StatusText } from "@/components/sgw";
import { TOOL_LABEL } from "@/features/agent-panel/labels";
import { aiStepName } from "@/lib/aiSteps";
import { classLabel, EFFORT_LABEL, MODEL_LABEL } from "./format";
import { Lede, LoadState } from "./parts";
import type { AiNode } from "./types";
import { useAiConfig } from "./useAdmin";

const Head = ({
  children,
  tip,
}: {
  children: string;
  tip: "effort" | "data_class_ceiling" | "allowed_tools";
}) => (
  <span className="inline-flex items-center gap-1">
    {children} <InfoTip term={tip} />
  </span>
);

const columns: DataColumn<AiNode>[] = [
  {
    id: "step",
    header: "Step",
    cell: (n) => (
      <>
        <span className="block font-medium" title={n.node}>
          {aiStepName(n.node)}
        </span>
        {n.citations && <span className="block text-[12px] text-muted">Cites sources</span>}
      </>
    ),
  },
  { id: "model", header: "Model", cell: (n) => MODEL_LABEL[n.model] },
  { id: "effort", header: <Head tip="effort">Effort</Head>, cell: (n) => EFFORT_LABEL[n.effort] },
  {
    id: "ceiling",
    header: <Head tip="data_class_ceiling">Data allowed</Head>,
    cell: (n) => classLabel(n.class_ceiling),
  },
  {
    id: "tools",
    header: <Head tip="allowed_tools">Lookups</Head>,
    cell: (n) =>
      n.allowed_tools.length === 0 ? (
        <span className="text-muted">None (text only)</span>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
          {n.allowed_tools.map((t) => (
            <li key={t}>{TOOL_LABEL[t] ?? t}</li>
          ))}
        </ul>
      ),
  },
  {
    id: "check",
    header: "Latest check",
    cell: (n) =>
      n.eval_result ? (
        <StatusText
          level={n.eval_result.passed ? "normal" : "elevated"}
          label={n.eval_result.passed ? "Met" : "Below target"}
        />
      ) : (
        <span className="text-muted">Not tested</span>
      ),
  },
];

export function AiConfigTab() {
  const config = useAiConfig();
  if (config.isPending || config.isError) return <LoadState query={config} what="AI settings" />;
  const { nodes, version } = config.data;
  return (
    <div className="flex flex-col pb-4">
      <Lede>Which model each AI step uses and what data it may see.</Lede>
      <div data-testid="ai-table">
        <DataTable
          data={nodes}
          columns={columns}
          getRowId={(n) => n.node}
          caption="AI steps and settings"
          rowTestId="ai-row"
          edge
        />
      </div>
      <SourceLine className="px-8 pt-3">{`Settings version ${version}.`}</SourceLine>
    </div>
  );
}
