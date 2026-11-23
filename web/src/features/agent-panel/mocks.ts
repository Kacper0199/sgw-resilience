import { HttpResponse, http } from "msw";
import { recordSitrepDraft } from "@/features/brief/mocks";
import { pickScript } from "./mocks/scripts";
import {
  copilotBeats,
  MOCK_SCENARIO_TIME,
  runTs,
  schedule,
  sitrepBeats,
  type TimedFrame,
} from "./mocks/timeline";
import type { Reference } from "./types";

interface MockRun {
  runId: string;
  threadId: string;
  graph: "copilot" | "sitrep";
  question: string;
  startedAt: number;
  frames: TimedFrame[];
  answer: string | null;
  path?: string;
  reason?: string;
  references?: Reference[];
  extras?: Record<string, unknown>;
  feedback: string | null;
  stop?: () => void;
}

interface MockThread {
  threadId: string;
  module: string;
  createdAt: string;
  runs: MockRun[];
}

const threads = new Map<string, MockThread>();
let counter = 0;
const tag = Math.random().toString(36).slice(2, 7);
const error = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message } }, { status });

const total = (r: MockRun) => r.frames[r.frames.length - 1]?.at ?? 0;
const finished = (r: MockRun) => Date.now() - r.startedAt >= total(r);

function frameJson(r: MockRun, f: TimedFrame) {
  return {
    v: 1,
    type: f.type,
    seq: f.seq,
    ledger_seq: null,
    run_id: r.runId,
    ns: [],
    ts: runTs(r.startedAt, f.at),
    scenario_time: MOCK_SCENARIO_TIME,
    run_mode: "replay",
    classification: "C1",
    payload: f.payload,
  };
}

function sseId(r: MockRun, seq: number): string {
  return `run:${r.runId}.1.${seq}`;
}

function stream(r: MockRun, afterSeq: number): Response {
  const enc = new TextEncoder();
  const timers: ReturnType<typeof setTimeout>[] = [];
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      r.stop = () => {
        for (const t of timers) clearTimeout(t);
        const at = Date.now() - r.startedAt;
        const end: TimedFrame = {
          seq: r.frames.length,
          at,
          type: "run_end",
          payload: { status: "cancelled" },
        };
        r.frames.push(end);
        try {
          controller.enqueue(
            enc.encode(
              `id: ${sseId(r, end.seq)}\nevent: run_end\ndata: ${JSON.stringify(frameJson(r, end))}\n\n`,
            ),
          );
          controller.close();
        } catch {
          // the reader went away
        }
      };
      for (const f of r.frames.filter((x) => x.seq > afterSeq)) {
        const wait = Math.max(0, r.startedAt + f.at - Date.now());
        timers.push(
          setTimeout(() => {
            try {
              controller.enqueue(
                enc.encode(
                  `id: ${sseId(r, f.seq)}\nevent: ${f.type}\ndata: ${JSON.stringify(frameJson(r, f))}\n\n`,
                ),
              );
              if (f.seq === r.frames.length - 1) controller.close();
            } catch {
              // the reader went away
            }
          }, wait),
        );
      }
    },
    cancel() {
      for (const t of timers) clearTimeout(t);
    },
  });
  return new HttpResponse(body, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
  });
}

function messagesOf(t: MockThread) {
  return t.runs.flatMap((r) => {
    const out = [
      {
        message_id: `${r.runId}.q`,
        role: "user",
        text: r.question,
        created_at: runTs(r.startedAt, 0),
        evidence_ids: [],
      },
    ];
    if (r.answer && finished(r)) {
      out.push({
        message_id: `${r.runId}.a`,
        role: "assistant",
        text: r.answer,
        created_at: runTs(r.startedAt, total(r)),
        evidence_ids: [],
        ...(r.path ? { path: r.path } : {}),
        ...(r.reason ? { reason: r.reason } : {}),
        ...(r.references ? { references: r.references } : {}),
        ...(r.extras ?? {}),
      });
    }
    return out;
  });
}

export const handlers = [
  http.post("/api/threads", async ({ request }) => {
    const body = (await request.json()) as { module: string };
    counter += 1;
    const t: MockThread = {
      threadId: `thr-mock-${tag}-${counter}`,
      module: body.module,
      createdAt: new Date().toISOString(),
      runs: [],
    };
    threads.set(t.threadId, t);
    return HttpResponse.json(
      { thread_id: t.threadId, created_at: t.createdAt, module: t.module },
      { status: 201 },
    );
  }),
  http.post("/api/threads/:threadId/runs", async ({ params, request }) => {
    const t = threads.get(String(params.threadId));
    if (!t) return error(404, "NOT_FOUND", "no such thread");
    const body = (await request.json()) as { graph: string; input: { question?: string } };
    if (t.runs.some((r) => !finished(r)))
      return error(409, "RUN_ACTIVE", "a run is already active on this thread");
    counter += 1;
    const startedAt = Date.now();
    let run: MockRun;
    if (body.graph === "copilot") {
      const question = String(body.input.question ?? "");
      const script = pickScript(question);
      run = {
        runId: `run-mock-${tag}-${counter}`,
        threadId: t.threadId,
        graph: "copilot",
        question,
        startedAt,
        frames: schedule(copilotBeats(question, script)),
        answer: script.text,
        path: script.path,
        reason: script.reason,
        references: script.references,
        extras: script.extras,
        feedback: null,
      };
    } else if (body.graph === "sitrep") {
      run = {
        runId: `run-mock-${tag}-${counter}`,
        threadId: t.threadId,
        graph: "sitrep",
        question: "Draft the situation report",
        startedAt,
        frames: schedule(sitrepBeats()),
        answer: null,
        feedback: null,
      };
      const id = run.runId;
      setTimeout(() => recordSitrepDraft(id), total(run));
    } else {
      return error(409, "GRAPH_NOT_AVAILABLE", "graph is not available yet");
    }
    t.runs.push(run);
    return HttpResponse.json(
      { run_id: run.runId, thread_id: t.threadId, events_url: `/api/threads/${t.threadId}/events` },
      { status: 202 },
    );
  }),
  http.get("/api/threads/:threadId/events", ({ params, request }) => {
    const t = threads.get(String(params.threadId));
    const run = t?.runs[t.runs.length - 1];
    if (!t || !run) return error(404, "RUN_NOT_FOUND", "no live run on this thread");
    const last = request.headers.get("last-event-id");
    const seen = last?.startsWith(`run:${run.runId}.`) ? Number(last.split(".").pop()) : -1;
    return stream(run, Number.isFinite(seen) ? seen : -1);
  }),
  http.get("/api/threads/:threadId/runs", () => HttpResponse.json([])),
  http.get("/api/threads/:threadId/messages", ({ params }) => {
    const t = threads.get(String(params.threadId));
    return t ? HttpResponse.json(messagesOf(t)) : HttpResponse.json([]);
  }),
  http.post("/api/threads/:threadId/runs/:runId/cancel", ({ params }) => {
    const run = threads.get(String(params.threadId))?.runs.find((r) => r.runId === params.runId);
    if (run && !finished(run)) {
      run.answer = null;
      run.stop?.();
    }
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/threads/:threadId/runs/:runId/feedback", async ({ params, request }) => {
    const run = threads.get(String(params.threadId))?.runs.find((r) => r.runId === params.runId);
    if (!run) return error(404, "NOT_FOUND", "no such run");
    run.feedback = ((await request.json()) as { rating: string }).rating;
    return new HttpResponse(null, { status: 204 });
  }),
];
