import { useSyncExternalStore } from "react";

const QUERY = "(min-width: 820px)";
const query = () => (typeof window.matchMedia === "function" ? window.matchMedia(QUERY) : null);

/** True from 820 px up, where the sources panel sits beside the chat; below it opens as a sheet. */
export function useWide(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mq = query();
      mq?.addEventListener("change", notify);
      return () => mq?.removeEventListener("change", notify);
    },
    () => query()?.matches ?? true,
    () => true,
  );
}
