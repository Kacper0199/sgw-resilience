export const OVERLAY = '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]';

/** A dialog, menu or toggletip is open or has the focus: page and shell shortcuts must not act behind it. */
export const overlayOpen = (e?: KeyboardEvent): boolean =>
  Boolean((e?.target as Element | null)?.closest?.(OVERLAY)) || document.querySelector(OVERLAY) !== null;
