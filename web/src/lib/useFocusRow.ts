import { useEffect } from "react";

const HIGHLIGHT_MS = 2400;
const SETTLE_MS = 1500;
const USER_INPUT = ["wheel", "touchstart", "keydown"] as const;

/**
 * Scrolls the table row `data-row-id={id}` to the middle and marks it `data-focused` for a moment, once `ready`.
 * The table may still grow while its detail rows load, so the row is centred again until the layout settles
 * or the person scrolls.
 */
export function useFocusRow(id: string | null, ready: boolean): void {
  useEffect(() => {
    if (!id || !ready) return;
    const cleanups: (() => void)[] = [];
    const frame = requestAnimationFrame(() => {
      const row = document.querySelector<HTMLElement>(`tr[data-row-id="${CSS.escape(id)}"]`);
      if (!row) return;
      const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
      const centre = (behavior: ScrollBehavior) => row.scrollIntoView?.({ block: "center", behavior });
      centre(calm ? "auto" : "smooth");
      row.dataset.focused = "true";

      const table = row.closest("table");
      const watch = table ? new ResizeObserver(() => centre("auto")) : null;
      if (table) watch?.observe(table);
      const stop = () => watch?.disconnect();
      for (const type of USER_INPUT) window.addEventListener(type, stop, { once: true, passive: true });
      const timers = [
        setTimeout(stop, SETTLE_MS),
        setTimeout(() => delete row.dataset.focused, HIGHLIGHT_MS),
      ];
      cleanups.push(() => {
        stop();
        for (const type of USER_INPUT) window.removeEventListener(type, stop);
        for (const t of timers) clearTimeout(t);
        delete row.dataset.focused;
      });
    });
    return () => {
      cancelAnimationFrame(frame);
      for (const clean of cleanups) clean();
    };
  }, [id, ready]);
}

/** Tailwind classes for a table container: the focused row fades in a soft blue. */
export const FOCUS_ROW_CLASS =
  "[&_tr]:transition-colors [&_tr]:duration-500 [&_tr[data-focused=true]]:bg-blue-soft [&_tr[data-focused=true]>td]:bg-blue-soft";
