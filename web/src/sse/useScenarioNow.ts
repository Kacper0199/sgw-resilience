import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useOps } from "./OpsStreamProvider";
import { scenarioNowMs } from "./reducer";

export function useScenario() {
  return useQuery({ queryKey: ["scenario"], queryFn: api.scenario, staleTime: 60_000 });
}

/** The scenario clock as an ISO string: stream frames first, the scenario endpoint until a frame arrives. */
export function useScenarioNow(): string | null {
  const ops = useOps();
  const scenario = useScenario();
  const [wall, setWall] = useState(() => Date.now());
  const speed = ops.speed ?? scenario.data?.speed ?? 0;
  const running = speed > 0;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setWall(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  const fromStream = scenarioNowMs(ops, wall, speed);
  if (fromStream !== null) return new Date(fromStream).toISOString();
  return scenario.data?.scenario_time ?? null;
}
