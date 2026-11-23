import type { GlossaryEntry } from "./glossary";

export const ASK_BRIEF_GLOSSARY = {
  copilot: {
    term: "Ask AI",
    text: "Answers questions from SGW procedures and platform data, with sources. It only reads: it can't change, send, or sign anything.",
  },
  read_only: {
    term: "Read-only",
    text: "The AI reads data and writes text. It can't sign, send, change records, or start anything.",
  },
  source_badge: {
    term: "Source",
    text: "The small label after a sentence names the document it came from. Select it to read the passage.",
  },
  not_in_documents: {
    term: "Not found in SGW documents",
    text: "Nothing in SGW documents or platform data answers the question, so the AI says so instead of guessing.",
  },
  from_platform_data: {
    term: "Answer from platform data",
    text: "No AI-written text: the answer lists what platform data and procedures say, word for word.",
  },
  findings_only: {
    term: "Sources only",
    text: "The answer failed its source check, so only the source passages are shown.",
  },
  unverified_record: {
    term: "Unverified field report",
    text: "A field report or ticket nobody has checked yet. Treat it as unconfirmed, never as procedure.",
  },
  how_i_got_this: {
    term: "Steps",
    text: "What the AI looked up, in order, so you can see where the answer came from.",
  },
  page_brief: {
    term: "Briefing",
    text: "The first page for executives: overall status, four numbers, decisions needing two teams, what changed and a draft situation report. Numbers come from platform data.",
  },
  brief_status: {
    term: "Overall status",
    text: "One word for how serious things are now. Set by fixed rules from outages and open deadlines, not by AI.",
  },
  outage_surge: {
    term: "Outage surge",
    text: "A county where outages rose far above usual, flagged by an automatic detector on public outage data. It also raises false alarms.",
  },
  forecast_actual: {
    term: "Forecast and actual",
    text: "Forecast: what the model expects, with an 80% range. Actual: what has been measured so far in the replay.",
  },
  sitrep: {
    term: "Situation report",
    text: "A short written summary of the situation. The AI drafts it; every number has a named source. A person must confirm it.",
  },
  promote: {
    term: "Confirm",
    text: "Confirming makes the draft the current situation report; one person confirms. Nothing is sent outside SGW.",
  },
} as const satisfies Record<string, GlossaryEntry>;
