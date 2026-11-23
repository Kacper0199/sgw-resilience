import type { WireFrame } from "@/contracts/wire.gen";
import { connectSse, nextBackoffMs, StreamAuthError } from "./client";
import { type Effect, reduceFrame } from "./reducer";
import type { OpsStore } from "./store";

export interface RunOptions {
  url: string;
  store: OpsStore;
  signal: AbortSignal;
  applyEffect: (effect: Effect) => void;
  onUnauthorized: () => void;
  staleAfterMs: number;
  watchdogMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

const realSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Keeps one ops stream alive: reconnects with Last-Event-ID and backoff, aborts a connection that went silent,
 * skips frames that do not parse, and stops (after telling the app) when the session ended.
 */
export async function runOpsStream(o: RunOptions): Promise<void> {
  const sleep = o.sleep ?? realSleep;
  const now = o.now ?? Date.now;
  let attempt = 0;

  while (!o.signal.aborted) {
    const connection = new AbortController();
    const abortWithOuter = () => connection.abort();
    o.signal.addEventListener("abort", abortWithOuter);
    const watchdog = setInterval(() => {
      const s = o.store.get();
      if (
        s.connection === "live" &&
        s.lastFrameWallMs !== null &&
        now() - s.lastFrameWallMs > o.staleAfterMs
      ) {
        o.store.patch({ connection: "stale" });
        connection.abort();
      }
    }, o.watchdogMs ?? 5000);

    o.store.patch({ connection: attempt === 0 ? "connecting" : "reconnecting" });
    try {
      await connectSse({
        url: o.url,
        lastEventId: o.store.get().lastEventId,
        signal: connection.signal,
        onOpen: () => {
          attempt = 0;
        },
        onMessage: (message) => {
          if (message.event === "message" || !message.data) return;
          let frame: WireFrame;
          try {
            frame = JSON.parse(message.data) as WireFrame;
          } catch {
            return;
          }
          const { state, effects } = reduceFrame(o.store.get(), frame, message.id, now());
          o.store.set(state);
          for (const e of effects) o.applyEffect(e);
        },
      });
    } catch (err) {
      if (err instanceof StreamAuthError) {
        o.store.patch({ connection: "idle" });
        o.onUnauthorized();
        return;
      }
    } finally {
      clearInterval(watchdog);
      o.signal.removeEventListener("abort", abortWithOuter);
    }
    if (o.signal.aborted) return;
    attempt += 1;
    await sleep(nextBackoffMs(attempt));
  }
}
