import { QueryClient } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { applyEffect } from "./effects";
import { runOpsStream } from "./runStream";
import { createOpsStore } from "./store";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

const frame = (id: string, type = "heartbeat", payload: object = {}) =>
  `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify({
    v: 1,
    type,
    seq: 1,
    ledger_seq: null,
    run_id: null,
    ns: [],
    ts: "2026-11-20T00:00:00Z",
    scenario_time: "2024-09-27T01:00:00Z",
    run_mode: "replay",
    classification: "C1",
    payload,
  })}\n\n`;

const sse = (body: string) =>
  new HttpResponse(body, { headers: { "content-type": "text/event-stream", "cache-control": "no-cache" } });

function harness(overrides: Partial<Parameters<typeof runOpsStream>[0]> = {}) {
  const controller = new AbortController();
  const store = createOpsStore();
  const sleeps: number[] = [];
  const onUnauthorized = vi.fn();
  const base = {
    url: "http://localhost/api/stream/ops",
    store,
    signal: controller.signal,
    applyEffect: vi.fn(),
    onUnauthorized,
    staleAfterMs: 60_000,
    sleep: async (ms: number) => {
      sleeps.push(ms);
    },
  };
  return {
    controller,
    store,
    sleeps,
    onUnauthorized,
    run: (extra = {}) => runOpsStream({ ...base, ...overrides, ...extra }),
  };
}

describe("runOpsStream", () => {
  it("reconnects with the last event id after the stream closes", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get("http://localhost/api/stream/ops", ({ request }) => {
        seen.push(request.headers.get("last-event-id"));
        return seen.length === 1 ? sse(frame("ops.1.1") + frame("ops.1.2")) : sse(frame("ops.1.3"));
      }),
    );
    const h = harness({
      sleep: async (ms: number) => {
        h.sleeps.push(ms);
        if (h.sleeps.length >= 2) h.controller.abort();
      },
    });
    await h.run();
    expect(seen).toEqual([null, "ops.1.2"]);
    expect(h.store.get().lastEventId).toBe("ops.1.3");
  });

  it("backs off with growing delays, capped, when the server refuses", async () => {
    let calls = 0;
    server.use(
      http.get("http://localhost/api/stream/ops", () => {
        calls += 1;
        return new HttpResponse(null, { status: 503 });
      }),
    );
    const h = harness({
      sleep: async (ms: number) => {
        h.sleeps.push(ms);
        if (h.sleeps.length >= 6) h.controller.abort();
      },
    });
    await h.run();
    expect(calls).toBe(6);
    expect(h.sleeps.slice(0, 4)).toEqual([2000, 4000, 8000, 15000]);
    expect(Math.max(...h.sleeps)).toBeLessThanOrEqual(15000);
  });

  it("stops and tells the app when the session ended (401)", async () => {
    let calls = 0;
    server.use(
      http.get("http://localhost/api/stream/ops", () => {
        calls += 1;
        return new HttpResponse(null, { status: 401 });
      }),
    );
    const h = harness();
    await h.run();
    expect(calls).toBe(1);
    expect(h.onUnauthorized).toHaveBeenCalledOnce();
    expect(h.sleeps).toEqual([]);
  });

  it("skips a frame that is not JSON without reconnecting for it", async () => {
    server.use(
      http.get("http://localhost/api/stream/ops", () =>
        sse(`id: ops.1.1\nevent: ledger\ndata: {not json\n\n${frame("ops.1.2")}`),
      ),
    );
    const h = harness({
      sleep: async (ms: number) => {
        h.sleeps.push(ms);
        h.controller.abort();
      },
    });
    await h.run();
    expect(h.store.get().lastEventId).toBe("ops.1.2");
    expect(h.sleeps).toHaveLength(1);
  });

  it("aborts a silent connection and reconnects with Last-Event-ID", async () => {
    const seen: (string | null)[] = [];
    const enc = new TextEncoder();
    vi.stubGlobal("fetch", (_url: string | URL, init?: RequestInit) => {
      seen.push(new Headers(init?.headers).get("last-event-id"));
      const first = seen.length === 1;
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(enc.encode(frame(first ? "ops.1.7" : "ops.1.8")));
          init?.signal?.addEventListener("abort", () => c.error(new DOMException("aborted", "AbortError")));
        },
      });
      return Promise.resolve(new Response(body, { headers: { "content-type": "text/event-stream" } }));
    });
    try {
      const h = harness({ staleAfterMs: 40, watchdogMs: 10 });
      const done = h.run();
      await vi.waitFor(() => expect(seen.length).toBeGreaterThanOrEqual(2), { timeout: 3000 });
      h.controller.abort();
      await done;
      expect(seen[1]).toBe("ops.1.7");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("applyEffect", () => {
  it("refetches the queue list and the affected card, not the other cards", async () => {
    const qc = new QueryClient();
    const fetcher = (key: string) => async () => ({ decision_case_id: key });
    await qc.fetchQuery({ queryKey: ["proposals"], queryFn: fetcher("list") });
    await qc.fetchQuery({ queryKey: ["proposals", "A"], queryFn: fetcher("A") });
    await qc.fetchQuery({ queryKey: ["proposals", "B"], queryFn: fetcher("B") });
    applyEffect(qc, { invalidate: ["proposals"], exact: true });
    applyEffect(qc, { invalidate: ["proposals", "A"] });
    const invalid = (key: string[]) =>
      qc.getQueryCache().find({ queryKey: key, exact: true })?.state.isInvalidated;
    expect(invalid(["proposals"])).toBe(true);
    expect(invalid(["proposals", "A"])).toBe(true);
    expect(invalid(["proposals", "B"])).toBe(false);
  });
});
