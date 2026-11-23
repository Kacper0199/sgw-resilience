import type { WireFrame } from "@/contracts/wire.gen";
import { notifyUnauthorized } from "@/lib/api";
import { connectSse, nextBackoffMs, StreamAuthError } from "@/sse/client";

const TERMINAL = new Set(["run_end", "run_error", "run_paused"]);
const realSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export interface FollowOptions {
  url: string;
  signal: AbortSignal;
  onFrame: (frame: WireFrame, sseId: string | undefined) => void;
  maxAttempts?: number;
  sleep?: (ms: number) => Promise<void>;
}

export type FollowResult = "finished" | "aborted" | "failed";

/**
 * Follows one run's stream until its terminal frame. A connection that ends early reconnects with
 * Last-Event-ID so no frame is lost or applied twice; frames that do not parse are skipped.
 */
export async function followRun(o: FollowOptions): Promise<FollowResult> {
  const sleep = o.sleep ?? realSleep;
  const max = o.maxAttempts ?? 4;
  let lastEventId: string | null = null;
  let seen = false;

  for (let attempt = 0; attempt < max; attempt += 1) {
    if (o.signal.aborted) return "aborted";
    try {
      await connectSse({
        url: o.url,
        lastEventId,
        signal: o.signal,
        onOpen: () => {},
        onMessage: (message) => {
          if (message.event === "message" || !message.data) return;
          let frame: WireFrame;
          try {
            frame = JSON.parse(message.data) as WireFrame;
          } catch {
            return;
          }
          if (message.id) lastEventId = message.id;
          o.onFrame(frame, message.id);
          if (TERMINAL.has(frame.type)) seen = true;
        },
      });
    } catch (err) {
      if (o.signal.aborted) return "aborted";
      if (err instanceof StreamAuthError) {
        notifyUnauthorized();
        return "failed";
      }
    }
    if (seen) return "finished";
    if (o.signal.aborted) return "aborted";
    await sleep(nextBackoffMs(attempt + 1));
  }
  return "failed";
}
