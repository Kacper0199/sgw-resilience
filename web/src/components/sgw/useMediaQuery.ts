import { useSyncExternalStore } from "react";

const list = (query: string) => (typeof window.matchMedia === "function" ? window.matchMedia(query) : null);

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mq = list(query);
      mq?.addEventListener("change", notify);
      return () => mq?.removeEventListener("change", notify);
    },
    () => list(query)?.matches ?? true,
    () => true,
  );
}
