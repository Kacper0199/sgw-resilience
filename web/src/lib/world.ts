import type { QueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

const KEPT = new Set(["me", "scenario"]);
let world = 0;
const watchers = new Set<() => void>();
const watch = (cb: () => void) => {
  watchers.add(cb);
  return () => {
    watchers.delete(cb);
  };
};

/** Which database the pages show; the page area remounts when it changes, in the same render as the other
 * updates, so no page renders the old database's ids again. */
export const useWorld = (): number => useSyncExternalStore(watch, () => world);

/** Another database is loaded (a demo moment or scenario): pages holding the old one's decisions must not
 * refetch them (their ids are gone). The decision list empties first (views built from it drop their cards),
 * the rest of the cache but the session and the clock is dropped, the page area remounts, then what is on
 * screen loads again. */
export function freshWorld(qc: QueryClient): void {
  const list = (key: readonly unknown[]) => key.length === 1 && key[0] === "proposals";
  qc.setQueriesData({ queryKey: ["proposals"], exact: true }, []);
  qc.removeQueries({ predicate: (q) => !KEPT.has(String(q.queryKey[0])) && !list(q.queryKey) });
  world += 1;
  for (const cb of watchers) cb();
  void qc.invalidateQueries();
}
