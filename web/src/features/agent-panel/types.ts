export type AnswerPath = "llm" | "m2" | "not_in_documents" | "guide";

/** Why the server gave no written answer (null when it did). */
export type AnswerReason =
  | "llm_unavailable"
  | "model_not_in_documents"
  | "out_of_scope"
  | "step_cap"
  | "checks_failed";

export interface SourceCite {
  n: number;
  citationId: string;
  section: string;
  pages: string;
  quote: string;
  unverified: boolean;
}

export type ReferenceKind =
  | "decision"
  | "asset"
  | "county"
  | "zone"
  | "advisory"
  | "crew"
  | "yard"
  | "readiness"
  | "clause"
  | "photo"
  | "surge"
  | "gauge"
  | "check";

/** An id the answer names, typed by the server from this run's evidence, so it can be opened. */
export interface Reference {
  kind: ReferenceKind;
  id: string;
  label: string;
}

/** Where an answer sends the reader: a page of the platform the signed-in role may open (the server filters by role). */
export interface AnswerLink {
  label: string;
  href: string;
  kind?: string;
}

/** A damage photo the answer shows: its thumbnail, where its detail opens and what it is. */
export interface AnswerPhoto {
  id: string;
  thumbUrl: string;
  href: string;
  caption: string;
  provenance: string | null;
}

/** What an answer adds to its text: pages to open, photos to look at, questions to ask next. */
export interface AnswerExtras {
  links: AnswerLink[];
  photos: AnswerPhoto[];
  suggestions: string[];
  /** Concrete readings of an unclear request, each a full question to send as it is. */
  didYouMean: string[];
  /** Set when Ask declined: an unrelated topic, a request to change something, or instruction-like text. */
  refusal: RefusalKind | null;
}

export type RefusalKind = "unrelated" | "write_action" | "injection";

export const NO_EXTRAS: AnswerExtras = {
  links: [],
  photos: [],
  suggestions: [],
  didYouMean: [],
  refusal: null,
};

export interface PlatformRow {
  id: string;
  text: string;
}

export interface ParsedAnswer {
  kind: AnswerPath;
  body: string;
  lead: string | null;
  citations: SourceCite[];
  platform: PlatformRow[];
}

export interface AnswerArtifact {
  text: string;
  path: AnswerPath | null;
  reason: AnswerReason | null;
  citations: SourceCite[];
  citationIds: string[];
  evidenceIds: string[];
  references: Reference[];
  extras: AnswerExtras;
  tainted: boolean;
  writeAttempts: number;
  at: string;
}

export interface SitrepDraft {
  tier: string;
  promotion: string;
  path: string;
  rendered: string;
  slots: Record<string, string>;
  tainted: boolean;
}

export type ToolStatus = "running" | "ok" | "refused" | "error";

export interface ToolCall {
  call: number;
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  /** The lookup ran and found nothing (no data, or not modelled for this scenario): not a source of the answer. */
  empty?: boolean;
}

export interface NodeState {
  node: string;
  status: "running" | "done";
  startedAt: string;
  endedAt?: string;
}

export interface LogEntry {
  seq: number;
  at: string;
  node: string | null;
  kind: "step" | "agent" | "tool" | "artifact" | "end" | "error";
  label: string;
  detail: string | null;
  status: "running" | "done" | "ok" | "refused" | "error";
}

export type RunStatus = "running" | "done" | "error" | "cancelled" | "paused";

export interface RunView {
  runId: string;
  threadId: string;
  graph: string;
  status: RunStatus;
  question: string | null;
  startedAt: string | null;
  endedAt: string | null;
  scenarioTime: string | null;
  nodes: NodeState[];
  tools: ToolCall[];
  log: LogEntry[];
  answer: AnswerArtifact | null;
  draft: SitrepDraft | null;
  alerts: string[];
  error: string | null;
  lastEventId: string | null;
}

export interface Turn {
  runId: string;
  question: string;
  askedAt: string;
  answerText: string | null;
  answerAt: string | null;
  answerPath: AnswerPath | null;
  answerReason: AnswerReason | null;
  /** Structured sources the server sent; empty when only the rendered "Sources" text is known. */
  citations: SourceCite[];
  evidenceIds: string[];
  references: Reference[];
  extras: AnswerExtras;
  run: RunView | null;
}
