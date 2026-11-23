import { useQuery } from "@tanstack/react-query";
import { parseAsString, useQueryState } from "nuqs";
import { get } from "@/lib/api";
import { adaptTrace } from "./adaptTrace";
import { useCanSeeTrace } from "./permission";
import type { WireRun } from "./wire";

export const useRunTrace = (runId: string | null) =>
  useQuery({
    queryKey: ["run-trace", runId],
    queryFn: async () => adaptTrace(await get<WireRun>(`/api/runs/${encodeURIComponent(runId as string)}`)),
    enabled: runId !== null,
    retry: false,
    staleTime: 30_000,
  });

const param = parseAsString.withOptions({ history: "push" });

/** The run whose trace is open, kept in the address (`?trace=`) so the sheet can be shared and survives a reload. */
export const useTraceTarget = () => useQueryState("trace", param);

/** A function that opens the trace of a run, or null when this person does not get to see traces. */
export function useOpenTrace(): ((runId: string) => void) | null {
  const allowed = useCanSeeTrace();
  const [, setTrace] = useTraceTarget();
  return allowed ? (runId) => void setTrace(runId) : null;
}
