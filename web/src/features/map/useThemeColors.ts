import { useSyncExternalStore } from "react";
import { mapColors } from "./geo";

type Colors = ReturnType<typeof mapColors>;

let cached: { theme: string; colors: Colors } | null = null;

function read(): Colors {
  const theme = document.documentElement.dataset.theme ?? "";
  if (!cached || cached.theme !== theme || !cached.colors.landUs) cached = { theme, colors: mapColors() };
  return cached.colors;
}

const subscribe = (cb: () => void) => {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => obs.disconnect();
};

/** Map colours resolved from the CSS variables; they change with the theme so layers never hold raw hex. */
export function useThemeColors(): Colors {
  return useSyncExternalStore(subscribe, read, read);
}
