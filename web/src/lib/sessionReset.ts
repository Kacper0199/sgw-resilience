const listeners = new Set<() => void>();

/** Register something that must forget what it learned in this session (sign-out, persona switch, scenario rewind). */
export function onSessionReset(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function resetSession(): void {
  for (const fn of listeners) fn();
}
