import { ShieldCheck } from "lucide-react";
import { EmptyState, InfoTip, LoadingState, StatusText } from "@/components/sgw";
import { formatEtZ } from "@/lib/time";
import { anomalyLabel, FAULT_LABEL, percentShare, plainCaveat, splitLabel } from "./format";
import { LoadFailed } from "./LoadFailed";
import { MeasureBar } from "./MeasureBar";
import type { EvalRow } from "./types";
import { useAnomalies, useAnomalyEvaluation } from "./useWater";

const found = (r: EvalRow) => Math.round(r.value * r.n);

function Fact({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] font-semibold text-muted">{label}</dt>
      <dd className="m-0 text-[16px] font-semibold tnum">{value}</dd>
      <dd className="m-0 text-[12px] text-muted">{note}</dd>
    </div>
  );
}

function Heading({ children, info }: { children: string; info?: "recall" | "seeded_faults" }) {
  return (
    <h3 className="m-0 mt-6 mb-2 flex items-center gap-1 border-b border-hair pb-1.5 text-[15px] leading-5 font-bold">
      {children}
      {info && <InfoTip term={info} />}
    </h3>
  );
}

function Results({ rows, caveats }: { rows: EvalRow[]; caveats: string[] }) {
  const recall = rows.find((r) => r.metric === "anomaly.recall_raw");
  const fa = rows.find((r) => r.metric === "anomaly.false_alarms_per_100_asset_days");
  const spoof = rows.find((r) => r.metric === "anomaly.spoof_flagged_share");
  const kinds = rows.filter((r) => r.metric.startsWith("anomaly.recall.")).sort((a, b) => a.value - b.value);
  if (!recall) return <EmptyState icon={ShieldCheck} title="No sensor test results yet." />;
  return (
    <div data-testid="sensor-results">
      <Heading info="recall">How well the checks catch faults</Heading>
      <p className="m-0 mb-1 text-[14px]" data-testid="recall-statement">
        <b>
          Caught {found(recall)} of {recall.n} test faults ({percentShare(recall.value)}).
        </b>
        {recall.passed === false && recall.threshold !== null && (
          <span className="font-semibold text-warn"> Below the {percentShare(recall.threshold)} target.</span>
        )}
      </p>
      <MeasureBar
        value={recall.value}
        low={recall.ci_low}
        high={recall.ci_high}
        target={recall.threshold}
        baseline={recall.baseline_value}
        baselineName={
          recall.baseline_name === "station low-pressure alarm alone" ? "Alarm only" : recall.baseline_name
        }
      />
      <dl className="m-0 mt-2 grid grid-cols-2 gap-x-6">
        {fa && (
          <Fact
            label="False alarms"
            value={`${fa.value.toFixed(0)} per 100 station-days`}
            note={`limit ${fa.threshold?.toFixed(0)}, tested on ${fa.n} station-days`}
          />
        )}
        {spoof && (
          <Fact
            label="Fake readings flagged"
            value={`${found(spoof)} of ${spoof.n}`}
            note={spoof.passed === false ? "target: all flagged" : "target met"}
          />
        )}
      </dl>
      <Heading info="seeded_faults">Faults caught by type</Heading>
      <table className="w-full border-collapse text-[13px]" aria-label="Faults caught by type">
        <thead>
          <tr className="text-left text-[12px] text-muted">
            <th className="h-8 border-b border-hair-strong font-semibold">Fault</th>
            <th className="h-8 border-b border-hair-strong text-end font-semibold">Caught</th>
            <th className="h-8 border-b border-hair-strong text-end font-semibold">Alarm only</th>
          </tr>
        </thead>
        <tbody>
          {kinds.map((k) => {
            const kind = k.metric.slice("anomaly.recall.".length);
            return (
              <tr key={k.metric} className="h-9 border-b border-hair" data-testid="fault-row">
                <td>{FAULT_LABEL[kind] ?? kind}</td>
                <td className="text-end tnum">
                  {found(k)} of {k.n}
                </td>
                <td className="text-end text-muted tnum">
                  {k.baseline_value === null ? "—" : `${Math.round(k.baseline_value * k.n)} of ${k.n}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {caveats.length > 0 && (
        <ul className="m-0 mt-3 list-disc pl-4 text-[12.5px] text-muted">
          {caveats.map((c) => (
            <li key={c}>{plainCaveat(c)}</li>
          ))}
        </ul>
      )}
      <p className="m-0 mt-3 text-[12px] text-muted">{`Tested on the ${splitLabel(recall.split)} set of synthetic faults.`}</p>
    </div>
  );
}

/** The sensor checks tab of System health: what needs attention now, then how well the checks catch faults. */
export function SensorContainer() {
  const evalQ = useAnomalyEvaluation();
  const alerts = useAnomalies();
  const open = (alerts.data ?? []).filter((a) => a.status === "open");
  return (
    <div className="px-8 py-6 max-[819px]:px-4">
      <div data-testid="sensor-alerts">
        {alerts.error ? (
          <LoadFailed
            thing="sensor alerts"
            icon={ShieldCheck}
            error={alerts.error}
            onRetry={() => void alerts.refetch()}
          />
        ) : alerts.isPending ? (
          <LoadingState label="Loading sensor alerts…" rows={1} />
        ) : open.length === 0 ? (
          <StatusText
            level="normal"
            label="No sensor needs attention right now."
            className="text-[16px] font-semibold text-ink"
          />
        ) : (
          <>
            <h3 className="m-0 mb-1 text-[16px] font-bold">Open sensor alerts</h3>
            <ul className="m-0 list-none p-0" aria-label="Open sensor alerts">
              {open.map((a) => (
                <li key={a.anomaly_id} className="flex items-baseline gap-3 border-b border-hair py-2.5">
                  <StatusText level="elevated" label={anomalyLabel(a.anomaly_class)} />
                  <span className="font-mono text-[12px] text-muted">{a.entity_id}</span>
                  <span className="ml-auto font-mono text-[12px] text-muted tnum">
                    {formatEtZ(a.detected_at)}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      {evalQ.error ? (
        <LoadFailed
          thing="test results"
          icon={ShieldCheck}
          error={evalQ.error}
          onRetry={() => void evalQ.refetch()}
        />
      ) : evalQ.isPending ? (
        <LoadingState label="Loading test results…" rows={3} />
      ) : (
        <Results rows={evalQ.data.metrics} caveats={evalQ.data.caveats ?? []} />
      )}
    </div>
  );
}
