import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { HEARTBEAT_INTERVAL_S, MISSED_HEARTBEATS_STALE } from "@/contracts/wire.gen";
import { notifyUnauthorized } from "@/lib/api";
import { applyEffect } from "./effects";
import { watchScenario } from "./refresh";
import { runOpsStream } from "./runStream";
import { createOpsStore, type OpsStore, useOpsState } from "./store";

const OpsStoreContext = createContext<OpsStore | null>(null);
const OpsRestartContext = createContext<() => void>(() => {});

export function useOpsStore(): OpsStore {
  const store = useContext(OpsStoreContext);
  if (!store) throw new Error("OpsStreamProvider is missing");
  return store;
}

export const useOps = () => useOpsState(useOpsStore());

/** Drops the ops stream and opens a fresh one, e.g. after the replay clock jumped. */
export const useOpsRestart = () => useContext(OpsRestartContext);

function StreamRunner({ url, store }: { url: string; store: OpsStore }) {
  const queryClient = useQueryClient();
  useEffect(() => {
    const controller = new AbortController();
    void runOpsStream({
      url,
      store,
      signal: controller.signal,
      applyEffect: (e) => applyEffect(queryClient, e),
      onUnauthorized: notifyUnauthorized,
      staleAfterMs: HEARTBEAT_INTERVAL_S * MISSED_HEARTBEATS_STALE * 1000,
    });
    return () => controller.abort();
  }, [queryClient, store, url]);
  return null;
}

export function OpsStreamProvider({
  children,
  url = "/api/stream/ops",
}: {
  children: React.ReactNode;
  url?: string;
}) {
  const store = useMemo(() => createOpsStore(), []);
  const queryClient = useQueryClient();
  useEffect(() => watchScenario(queryClient), [queryClient]);
  const [epoch, setEpoch] = useState(0);
  const restart = useCallback(() => setEpoch((n) => n + 1), []);

  return (
    <OpsStoreContext.Provider value={store}>
      <OpsRestartContext.Provider value={restart}>
        <StreamRunner key={epoch} url={url} store={store} />
        {children}
      </OpsRestartContext.Provider>
    </OpsStoreContext.Provider>
  );
}
