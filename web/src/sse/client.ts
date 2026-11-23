import { createSseParser, type SseMessage } from "./parser";

export class StreamAuthError extends Error {}

export interface ConnectOptions {
  url: string;
  lastEventId: string | null;
  signal: AbortSignal;
  onOpen: () => void;
  onMessage: (message: SseMessage) => void;
}

/** Reads one SSE connection until it ends. Sends Last-Event-ID so the server continues after the last seen frame. */
export async function connectSse({
  url,
  lastEventId,
  signal,
  onOpen,
  onMessage,
}: ConnectOptions): Promise<void> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (lastEventId) headers["Last-Event-ID"] = lastEventId;
  const res = await fetch(url, { headers, signal, credentials: "same-origin", cache: "no-store" });
  if (res.status === 401) throw new StreamAuthError("session ended");
  if (!res.ok || !res.body) throw new Error(`stream refused: HTTP ${res.status}`);
  onOpen();
  const parser = createSseParser(onMessage);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    parser.push(value);
  }
}

export const nextBackoffMs = (attempt: number): number => Math.min(15_000, 1000 * 2 ** Math.min(attempt, 4));
