import { useSyncExternalStore } from "react";
import { initialOpsState, type OpsState } from "./reducer";

type Listener = () => void;

/** A minimal external store so the stream can update one state object without a state library. */
export function createOpsStore() {
  let state: OpsState = initialOpsState;
  const listeners = new Set<Listener>();
  return {
    get: () => state,
    set(next: OpsState) {
      state = next;
      for (const l of listeners) l();
    },
    patch(partial: Partial<OpsState>) {
      state = { ...state, ...partial };
      for (const l of listeners) l();
    },
    subscribe(l: Listener) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

export type OpsStore = ReturnType<typeof createOpsStore>;

export function useOpsState(store: OpsStore): OpsState {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}
