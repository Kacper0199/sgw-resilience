import { useCallback, useSyncExternalStore } from "react";

const KEY = "sgw.transparency";

const read = (): boolean => document.documentElement.dataset.transparency === "reduced";
const subscribe = (cb: () => void) => {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-transparency"] });
  return () => obs.disconnect();
};

/** The in-app "Reduce transparency" setting: Safari cannot report the system one, so the choice is stored here. */
export function useReducedTransparency(): [boolean, (on: boolean) => void] {
  const reduced = useSyncExternalStore(subscribe, read, () => false);
  const set = useCallback((on: boolean) => {
    if (on) document.documentElement.dataset.transparency = "reduced";
    else delete document.documentElement.dataset.transparency;
    try {
      if (on) localStorage.setItem(KEY, "reduced");
      else localStorage.removeItem(KEY);
    } catch {
      /* storage unavailable: the choice lasts for this page only */
    }
  }, []);
  return [reduced, set];
}
