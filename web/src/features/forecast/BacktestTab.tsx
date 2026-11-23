import { ChevronRight, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { type DataColumn, DataTable, EmptyState, LoadingState, StatusText } from "@/components/sgw";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { type Backtest, baselineLabel, parseBacktest, type SummaryRow } from "./backtest";
import { DEFAULT_REPORT, useEvaluation } from "./data";
import { withEdges } from "./edge";
import { count, percent } from "./format";
import { SectionHead } from "./SectionHead";

const num = "text-right tnum";

function Best({
  value,
  others,
  format,
  className,
}: {
  value: number | null;
  others: (number | null)[];
  format: (n: number) => string;
  className?: string;
}) {
  if (value === null) return <TableCell className={cn(num, "text-muted", className)}>–</TableCell>;
  const best = Math.min(value, ...others.filter((o): o is number => o !== null)) === value;
  return <TableCell className={cn(num, best && "font-semibold", className)}>{format(value)}</TableCell>;
}

function Row({ s, bt }: { s: Backtest["storms"][number]; bt: Backtest }) {
  const c = s.county;
  const t = s.total;
  const w = s.worstMiss;
  return (
    <TableRow data-testid="backtest-detail-row">
      <TableCell className="font-medium whitespace-nowrap">{s.name}</TableCell>
      <Best
        value={c?.model ?? null}
        others={[c?.wind ?? null, c?.curve ?? null]}
        format={count}
        className="border-l border-hair"
      />
      <Best value={c?.wind ?? null} others={[c?.model ?? null, c?.curve ?? null]} format={count} />
      {bt.countyCurve && (
        <Best value={c?.curve ?? null} others={[c?.model ?? null, c?.wind ?? null]} format={count} />
      )}
      <Best
        value={t?.model ?? null}
        others={[t?.wind ?? null, t?.curve ?? null]}
        format={percent}
        className="border-l border-hair"
      />
      <Best value={t?.wind ?? null} others={[t?.model ?? null, t?.curve ?? null]} format={percent} />
      {bt.totalCurve && (
        <Best value={t?.curve ?? null} others={[t?.model ?? null, t?.wind ?? null]} format={percent} />
      )}
      <TableCell className={cn(num, "border-l border-hair")}>
        {s.coverage80 ? percent(s.coverage80.value) : "–"}
      </TableCell>
      <Best
        value={w?.model ?? null}
        others={[w?.wind ?? null]}
        format={count}
        className="border-l border-hair"
      />
      <Best value={w?.wind ?? null} others={[w?.model ?? null]} format={count} />
    </TableRow>
  );
}

function BacktestDetail({ bt }: { bt: Backtest }) {
  const wind = bt.windName ?? "Wind rule";
  const head = "h-8 text-right";
  return (
    <div className="overflow-x-auto px-5" data-testid="backtest-detail">
      <Table>
        <TableHeader>
          <TableRow className="h-8 hover:bg-transparent">
            <TableHead rowSpan={2} className="align-bottom">
              Storm
            </TableHead>
            <TableHead colSpan={2 + Number(bt.countyCurve)} className="border-l border-hair text-center">
              Error per county (customers)
            </TableHead>
            <TableHead colSpan={2 + Number(bt.totalCurve)} className="border-l border-hair text-center">
              Total outages off by
            </TableHead>
            <TableHead className="border-l border-hair text-right align-bottom" rowSpan={2}>
              Counties in 80% range
            </TableHead>
            <TableHead colSpan={2} className="border-l border-hair text-center">
              Worst miss (customers)
            </TableHead>
          </TableRow>
          <TableRow className="h-8 hover:bg-transparent">
            <ColHeads
              wind={wind}
              curve={bt.countyCurve ? (bt.curveName ?? "Damage curve") : null}
              head={head}
            />
            <ColHeads
              wind={wind}
              curve={bt.totalCurve ? (bt.curveName ?? "Damage curve") : null}
              head={head}
            />
            <ColHeads wind={wind} curve={null} head={head} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {bt.storms.map((s) => (
            <Row key={s.key} s={s} bt={bt} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CompactRow({ s, bt }: { s: Backtest["storms"][number]; bt: Backtest }) {
  const t = s.total;
  return (
    <TableRow data-testid="backtest-row">
      <TableCell className="font-medium whitespace-nowrap">{s.name}</TableCell>
      <Best value={t?.model ?? null} others={[t?.wind ?? null, t?.curve ?? null]} format={percent} />
      <Best value={t?.wind ?? null} others={[t?.model ?? null, t?.curve ?? null]} format={percent} />
      {bt.totalCurve && (
        <Best value={t?.curve ?? null} others={[t?.model ?? null, t?.wind ?? null]} format={percent} />
      )}
      <TableCell className={num}>{s.coverage80 ? percent(s.coverage80.value) : "–"}</TableCell>
    </TableRow>
  );
}

/** The two or three numbers that matter: how far off the total was for each method, and how often the 80% range held. */
export function BacktestTable({ bt }: { bt: Backtest }) {
  const wind = bt.windName ?? "Wind rule";
  const head = "h-8 text-right";
  return (
    <div className="overflow-x-auto px-5" data-testid="backtest-table">
      <Table>
        <TableHeader>
          <TableRow className="h-8 hover:bg-transparent">
            <TableHead rowSpan={2} className="align-bottom">
              Storm
            </TableHead>
            <TableHead colSpan={2 + Number(bt.totalCurve)} className="border-l border-hair text-center">
              Total outages off by
            </TableHead>
            <TableHead className="border-l border-hair text-right align-bottom" rowSpan={2}>
              Counties in 80% range
            </TableHead>
          </TableRow>
          <TableRow className="h-8 hover:bg-transparent">
            <ColHeads
              wind={wind}
              curve={bt.totalCurve ? (bt.curveName ?? "Damage curve") : null}
              head={head}
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          {bt.storms.map((s) => (
            <CompactRow key={s.key} s={s} bt={bt} />
          ))}
        </TableBody>
      </Table>
      <Collapsible className="mt-2">
        <CollapsibleTrigger className="group flex h-9 items-center gap-1.5 text-[13px] font-semibold text-blue-ink hover:underline">
          <ChevronRight
            className="size-3.5 transition-transform group-data-[state=open]:rotate-90"
            aria-hidden
          />
          More measures
        </CollapsibleTrigger>
        <CollapsibleContent className="-mx-5">
          <BacktestDetail bt={bt} />
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

function ColHeads({ wind, curve, head }: { wind: string; curve: string | null; head: string }) {
  return (
    <>
      <TableHead className={cn(head, "border-l border-hair")}>Forecast</TableHead>
      <TableHead className={head}>{wind}</TableHead>
      {curve && <TableHead className={head}>{curve}</TableHead>}
    </>
  );
}

const SUMMARY_COLUMNS: DataColumn<SummaryRow>[] = [
  {
    id: "measure",
    header: "Measure",
    cell: (r) => (
      <div className="py-1">
        <div>{r.label}</div>
        {r.baseline && (
          <div className="text-[12px] text-muted">Compared with {baselineLabel(r.baseline)}</div>
        )}
      </div>
    ),
  },
  {
    id: "value",
    header: "Result",
    align: "end",
    cell: (r) => (
      <span className="tnum">
        <span className="font-semibold">
          {Number.isInteger(r.value) ? count(r.value) : r.value.toFixed(2)}
        </span>{" "}
        <span className="text-muted">{r.unit}</span>
      </span>
    ),
  },
  {
    id: "target",
    header: "Against target",
    cell: (r) =>
      r.passed === null ? null : r.passed ? (
        <StatusText level="normal" label="Met" />
      ) : (
        <StatusText level="elevated" label="Below target" />
      ),
  },
];

export function BacktestTab({ report = DEFAULT_REPORT }: { report?: string }) {
  const evaluation = useEvaluation(report);
  const bt = useMemo(() => (evaluation.data ? parseBacktest(evaluation.data) : null), [evaluation.data]);

  if (evaluation.isPending) {
    return <LoadingState rows={5} label="Loading the track record" className="px-8 pt-4" />;
  }
  if (!bt || !evaluation.data) {
    return <EmptyState icon={TriangleAlert} title="The track record isn't available yet." />;
  }
  return (
    <div data-testid="backtest">
      <SectionHead
        className="pt-6"
        title={`${bt.storms.length} past storms, each forecast without seeing what happened`}
        info="loso"
      />
      <BacktestTable bt={bt} />
      <div className="px-8 pt-3">
        {bt.coverageMisses.length > 0 && (
          <p data-testid="coverage-caveat" className="m-0 text-[12px] text-muted">
            The 80% range should contain about 80% of counties.{" "}
            {bt.coverageMisses.map((m) => `${m.storm}: ${percent(m.value)}`).join("; ")}.
          </p>
        )}
        <p className="m-0 mt-1 text-[12px] text-muted">
          Lower is better, except "Counties in 80% range", which should be near 80%. The best method is in
          bold.
        </p>
      </div>
      <SectionHead title="Across all storms" info="backtest" />
      <DataTable
        caption="Across all storms"
        data={bt.summary}
        getRowId={(r) => r.metric}
        rowTestId="backtest-summary"
        columns={withEdges(SUMMARY_COLUMNS)}
      />
      <p className="m-0 px-8 pt-4 text-[12px] text-muted">
        Tested on {bt.storms.length} past storms, each left out of training. Details in{" "}
        <Link to="/health?tab=models" className="font-semibold text-blue-ink hover:underline">
          System health → Models
        </Link>
        .
      </p>
    </div>
  );
}
