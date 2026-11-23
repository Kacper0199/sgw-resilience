import { afterEach, vi } from "vitest";
import { setUnauthorizedHandler } from "@/lib/api";
import { followRun } from "./followRun";

const enc = new TextEncoder();
const sse = (id: string, type: string, seq: number) =>
  `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify({ v: 1, type, seq, ts: "2024-09-27T01:00:00Z", payload: {} })}\n\n`;

const body = (chunks: string[]) =>
  new ReadableStream<Uint8Array>({
    start(c) {
      for (const k of chunks) c.enqueue(enc.encode(k));
      c.close();
    },
  });

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

const noWait = () => Promise.resolve();

describe("followRun", () => {
  it("reconnects with Last-Event-ID after a dropped connection and applies each frame once", async () => {
    const seen: string[] = [];
    const sent: (string | null)[] = [];
    const answers = [
      body([sse("run:r.1.0", "run_start", 0), sse("run:r.1.1", "step", 1)]),
      body([sse("run:r.1.2", "run_end", 2)]),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        sent.push(new Headers(init.headers).get("Last-Event-ID"));
        return new Response(answers.shift(), { status: 200 });
      }),
    );
    const result = await followRun({
      url: "/api/threads/t/events",
      signal: new AbortController().signal,
      onFrame: (f) => seen.push(f.type),
      sleep: noWait,
    });
    expect(result).toBe("finished");
    expect(seen).toEqual(["run_start", "step", "run_end"]);
    expect(sent).toEqual([null, "run:r.1.1"]);
  });

  it("skips a frame that is not JSON without dropping the stream", async () => {
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(body(["id: x\nevent: step\ndata: {not json\n\n", sse("run:r.1.1", "run_end", 1)]), {
            status: 200,
          }),
      ),
    );
    const result = await followRun({
      url: "/e",
      signal: new AbortController().signal,
      onFrame: (f) => seen.push(f.type),
      sleep: noWait,
    });
    expect(result).toBe("finished");
    expect(seen).toEqual(["run_end"]);
  });

  it("tells the app the session ended on a 401 and stops", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    const fetchMock = vi.fn(async () => new Response("", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await followRun({
      url: "/e",
      signal: new AbortController().signal,
      onFrame: () => {},
      sleep: noWait,
    });
    expect(result).toBe("failed");
    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("gives up after the attempt limit when the stream keeps ending early", async () => {
    const fetchMock = vi.fn(async () => new Response(body([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await followRun({
      url: "/e",
      signal: new AbortController().signal,
      onFrame: () => {},
      maxAttempts: 3,
      sleep: noWait,
    });
    expect(result).toBe("failed");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("reports aborted when the caller aborts", async () => {
    const ctl = new AbortController();
    ctl.abort();
    const result = await followRun({ url: "/e", signal: ctl.signal, onFrame: () => {}, sleep: noWait });
    expect(result).toBe("aborted");
  });
});
