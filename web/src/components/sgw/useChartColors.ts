import { useSyncExternalStore } from "react";

const read = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const resolve = () => ({
  series: [read("--chart-1"), read("--chart-2"), read("--chart-3")],
  bandWide: read("--chart-band-wide"),
  bandMid: read("--chart-band-mid"),
  bandCore: read("--chart-band-core"),
  median: read("--chart-median"),
  track: read("--chart-track"),
});

let snapshot: ReturnType<typeof resolve> | null = null;

const current = () => {
  if (!snapshot?.bandCore) snapshot = resolve();
  return snapshot;
};

const subscribe = (notify: () => void) => {
  const observer = new MutationObserver(() => {
    snapshot = resolve();
    notify();
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
};

/** Chart colours resolved from the --chart-* tokens; they follow the theme so no chart holds a raw hex. */
export function useChartColors() {
  return useSyncExternalStore(subscribe, current, current);
}
