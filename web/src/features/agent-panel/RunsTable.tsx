import { StatusIndicator } from "@/components/sgw";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatZ } from "@/lib/time";
import { elapsedMs, formatElapsed, PATH_LABEL, runPath, STATUS_WORD } from "./runFormat";
import type { RunView } from "./types";

interface Props {
  runs: RunView[];
  selectedId: string | null;
  onSelect: (runId: string) => void;
}

const tone = (s: RunView["status"]) =>
  s === "done" ? "ok" : s === "error" ? "missed" : s === "running" ? "running" : "idle";

export function RunsTable({ runs, selectedId, onSelect }: Props) {
  return (
    <div className="overflow-x-auto">
      <Table aria-label="Activity">
        <TableHeader>
          <TableRow className="h-9 hover:bg-transparent">
            <TableHead>Question</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="max-[1199px]:hidden">Answer</TableHead>
            <TableHead className="text-right">Started</TableHead>
            <TableHead className="text-right">Duration</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((r) => {
            const path = runPath(r);
            const selected = r.runId === selectedId;
            return (
              <TableRow
                key={r.runId}
                data-testid="run-row"
                data-selected={selected}
                className={cn(
                  "h-11 cursor-pointer border-b border-hair",
                  selected && "bg-selected shadow-[inset_3px_0_0_var(--blue)] hover:bg-selected",
                )}
              >
                <TableCell className="max-w-0 w-[40%]">
                  <button
                    type="button"
                    onClick={() => onSelect(r.runId)}
                    aria-pressed={selected}
                    className="block w-full truncate text-left text-[13px] font-medium text-ink"
                  >
                    {r.question || "Untitled question"}
                  </button>
                </TableCell>
                <TableCell>
                  <StatusIndicator status={tone(r.status)} label={STATUS_WORD[r.status]} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted max-[1199px]:hidden">
                  {path ? PATH_LABEL[path] : "No answer"}
                </TableCell>
                <TableCell className="text-right font-mono text-[11.5px] whitespace-nowrap text-muted">
                  {r.startedAt ? formatZ(r.startedAt) : "-"}
                </TableCell>
                <TableCell className="text-right font-mono text-[11.5px] whitespace-nowrap text-muted">
                  {formatElapsed(elapsedMs(r))}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
