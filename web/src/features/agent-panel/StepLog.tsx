import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { offsetLabel } from "./runFormat";
import type { RunView } from "./types";

/** The run's last two entries repeat what the table row and "Finish the answer" already say. */
const CLOSING_ECHO: ReadonlySet<string> = new Set(["end:Done", "artifact:Answer ready"]);

export function StepLog({ run }: { run: RunView }) {
  const log = run.log.filter(
    (e, i) =>
      (e.label !== run.log[i - 1]?.label || e.kind === "tool") && !CLOSING_ECHO.has(`${e.kind}:${e.label}`),
  );
  const withDetail = log.some((e) => e.detail);
  if (log.length === 0) return <p className="m-0 text-[13px] text-muted">No steps yet.</p>;
  return (
    <div className="overflow-x-auto">
      <Table aria-label="Step details">
        <TableHeader>
          <TableRow className="h-8 hover:bg-transparent">
            <TableHead className="w-16 px-0">Time</TableHead>
            <TableHead>Step</TableHead>
            {withDetail && <TableHead>Detail</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {log.map((e) => (
            <TableRow key={`${e.seq}-${e.label}`} className="h-8 border-b border-hair last:border-b-0">
              <TableCell className="px-0 font-mono text-[11.5px] whitespace-nowrap text-muted">
                {offsetLabel(run, e.at)}
              </TableCell>
              <TableCell
                className={cn(
                  "whitespace-nowrap",
                  (e.status === "error" || e.status === "refused") && "text-error",
                )}
              >
                {e.label}
              </TableCell>
              {withDetail && (
                <TableCell className="max-w-0 truncate text-muted" title={e.detail ?? undefined}>
                  {e.detail}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
