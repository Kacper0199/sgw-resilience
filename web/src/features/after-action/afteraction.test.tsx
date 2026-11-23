import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { api, type Me } from "@/lib/api";
import { scenario } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import AfterActionPage from "./AfterActionPage";
import { BreakGlassTab } from "./BreakGlassTab";
import { ClocksTab } from "./ClocksTab";
import { entryLabels, errorText, kindLabel, marginText, personaTitle, subjectId } from "./format";
import { review, TAMPERED_SEQ, timeline } from "./mocks";
import { ReportTab } from "./ReportTab";
import { ScorecardTab } from "./ScorecardTab";
import { reviewSentence } from "./Summary";
import { TimelineTab } from "./TimelineTab";
import { VerifyPanel } from "./VerifyPanel";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  mockState.userId = "audit_01";
});
afterEach(() => server.resetHandlers());

function show(ui: React.ReactElement, me?: Me) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (me) qc.setQueryData(ME_KEY, me);
  return render(
    <QueryClientProvider client={qc}>
      <NuqsTestingAdapter>
        <MemoryRouter>{ui}</MemoryRouter>
      </NuqsTestingAdapter>
    </QueryClientProvider>,
  );
}

const intact = review(null);
const broken = review(TAMPERED_SEQ);

describe("format", () => {
  it("states an estimate error in words, signed against the actual", () => {
    expect(errorText(3.1)).toBe("3.1 h later than actual");
    expect(errorText(-0.3)).toBe("0.3 h earlier than actual");
    expect(errorText(0)).toBe("Exact");
  });

  it("states a clock margin against the deadline", () => {
    expect(marginText(54)).toBe("54 m before the deadline");
    expect(marginText(-36)).toBe("36 m after the deadline");
    expect(marginText(null)).toBe("");
  });

  it("turns ledger kinds, people and subjects into plain words", () => {
    expect(kindLabel("break_glass_used")).toBe("Emergency approval used");
    expect(kindLabel("some_new_kind")).toBe("Some new kind");
    expect(personaTitle("ic_01")).toBe("Incident Commander");
    expect(personaTitle("system")).toBe("System");
    expect(subjectId("proposal:PRP-CREW-AIK-0926A")).toBe("PRP-CREW-AIK-0926A");
  });
});

describe("voided signatures", () => {
  const entry = (seq: number, kind: string, actor: string, subject = "proposal:PRP-CREW-AIK-0926A") => ({
    seq,
    occurred_at: `2024-09-26T0${seq}:00:00Z`,
    kind,
    actor_id: actor,
    subject,
  });

  it("marks a signature voided when a new advisory revised the decision after it", () => {
    const labels = entryLabels([
      entry(1, "proposal_created", "ops_dm_01"),
      entry(2, "approval_recorded", "ic_01"),
      entry(3, "proposal_revised", "system:clock-replanner"),
      entry(4, "approval_recorded", "ic_01"),
      entry(5, "approval_recorded", "wtr_lead_01", "proposal:PRP-OTHER"),
    ]);
    expect(labels.get(2)).toBe("Signature voided — a new advisory moved the deadline");
    expect(labels.get(4)).toBe("Signature recorded");
    expect(labels.get(5)).toBe("Signature recorded");
    expect(labels.get(3)).toBe("Decision updated");
  });

  it("says the decision changed when a person revised it", () => {
    const labels = entryLabels([
      entry(1, "approval_recorded", "ic_01"),
      entry(2, "proposal_revised", "ops_dm_01"),
    ]);
    expect(labels.get(1)).toBe("Signature voided — the decision changed");
  });
});

describe("review sentence", () => {
  it("counts met, missed and open clocks from the rows and says what needs attention", () => {
    const met = intact.clocks.filter((c) => c.outcome === "met").length;
    const missed = intact.clocks.filter((c) => c.outcome === "missed").length;
    const s = reviewSentence(intact);
    expect(s).toContain("The audit log passed its check.");
    expect(s).toContain(`${met} met, ${missed} missed`);
    expect(s).toContain(`${intact.break_glass.length} emergency approvals`);
  });

  it("leads with the broken ledger and the first bad entry", () => {
    expect(reviewSentence(broken)).toBe(
      `The audit log fails its check from entry ${TAMPERED_SEQ}. Entries from there on can't be trusted.`,
    );
  });
});

describe("Clocks", () => {
  it("lists every clock in decide-by order with its result and margin", () => {
    show(<ClocksTab clocks={intact.clocks} />);
    const rows = screen.getAllByTestId("clock-row");
    expect(rows).toHaveLength(intact.clocks.length);
    expect(within(rows[0] as HTMLElement).getByText("Met")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Missed")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("36 m after the deadline")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("By emergency approval")).toBeInTheDocument();
  });

  it("filters to missed clocks and says so when a filter has no rows", () => {
    show(<ClocksTab clocks={intact.clocks} />);
    fireEvent.click(screen.getByRole("button", { name: /^Missed/ }));
    expect(screen.getAllByTestId("clock-row")).toHaveLength(
      intact.clocks.filter((c) => c.outcome === "missed").length,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Still open/ }));
    expect(screen.getAllByTestId("clock-row")).toHaveLength(1);
    show(<ClocksTab clocks={[]} />);
    expect(screen.getByText("No deadlines match this filter.")).toBeInTheDocument();
  });

  it("shows a clock that cannot be verified when the chain is broken before its decision", () => {
    const clocks = broken.clocks.filter((c) => c.decision_case_id === "DC-D3-BWN-Z3");
    show(<ClocksTab clocks={clocks} />);
    expect(screen.getByText("Can't be checked")).toBeInTheDocument();
  });
});

describe("Break-glass", () => {
  it("flags a late co-sign with how late and a waiting co-sign with its due time", () => {
    show(<BreakGlassTab uses={intact.break_glass} />);
    const rows = screen.getAllByTestId("break-glass-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByText("Co-signed late")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText(/35 m after the window closed/)).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText(/Approver unreachable/)).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Waiting for co-sign")).toBeInTheDocument();
    expect(rows.every((r) => r.getAttribute("data-flagged") === "true")).toBe(true);
  });

  it("warns when the ledger and the break-glass record disagree", () => {
    const first = intact.break_glass[0];
    if (!first) throw new Error("mock has a break-glass use");
    show(<BreakGlassTab uses={[{ ...first, table_agrees: false }]} />);
    expect(screen.getByRole("alert")).toHaveTextContent("disagree");
  });

  it("says plainly when nothing was used", () => {
    show(<BreakGlassTab uses={[]} />);
    expect(screen.getByText("No emergency approvals in this event.")).toBeInTheDocument();
  });
});

describe("Scorecard", () => {
  it("shows the whole-territory error beside the historical analog and each estimate against actual", () => {
    if (!intact.scorecard) throw new Error("mock has a scorecard");
    show(<ScorecardTab card={intact.scorecard} />);
    const rows = screen.getAllByTestId("score-row");
    expect(rows).toHaveLength(intact.scorecard.estimates.length);
    expect(within(rows[0] as HTMLElement).getByText("Whole service area")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("0.3 h earlier than actual")).toBeInTheDocument();
    expect(screen.getByTestId("analog-line")).toHaveTextContent(
      "1.5 h for the whole service area, 29.8 h typical for areas",
    );
    expect(screen.getByText(/simulated actual, not the replay curve/)).toBeInTheDocument();
  });

  it("has an empty state without a published estimate", () => {
    show(<ScorecardTab card={null} />);
    expect(screen.getByText("No published estimate to compare yet.")).toBeInTheDocument();
  });
});

describe("Timeline", () => {
  it("shows entries in ledger order with plain labels and day headings", () => {
    show(<TimelineTab entries={[...timeline].reverse()} chain={intact.chain} />);
    const rows = screen.getAllByTestId("timeline-row");
    expect(rows[0]).toHaveTextContent("Decision proposed");
    expect(rows[0]).toHaveTextContent("#311");
    expect(screen.queryByTestId("untrusted-note")).not.toBeInTheDocument();
  });

  it("marks every entry from the first bad one as not trusted", () => {
    show(<TimelineTab entries={timeline} chain={broken.chain} />);
    const rows = screen.getAllByTestId("timeline-row");
    const untrusted = rows.filter((r) => r.getAttribute("data-untrusted") === "true");
    expect(untrusted).toHaveLength(timeline.filter((e) => e.seq >= TAMPERED_SEQ).length);
    expect(untrusted[0]).toHaveTextContent("Not trusted");
    expect(screen.getByTestId("untrusted-note")).toHaveTextContent(`Entries from ${TAMPERED_SEQ} on`);
  });
});

describe("Report draft", () => {
  it("carries the rule, the draft-not-filed mark, the filer's notes and the exercise footer", () => {
    if (!intact.sc_report) throw new Error("mock has a report");
    show(<ReportTab report={intact.sc_report} chainOk />);
    expect(screen.getByText(intact.sc_report.citation)).toBeInTheDocument();
    expect(screen.getByText("Draft, not filed")).toBeInTheDocument();
    expect(screen.getAllByTestId("report-row")).toHaveLength(intact.sc_report.counties.length + 1);
    expect(screen.getByText(/enter them before filing/)).toBeInTheDocument();
    expect(screen.getByText(/Exercise with synthetic data, not for operational use/)).toBeInTheDocument();
    expect(screen.queryByText(/Do not use/)).not.toBeInTheDocument();
  });

  it("carries the broken-chain notice on the draft", () => {
    if (!broken.sc_report) throw new Error("mock has a report");
    show(<ReportTab report={broken.sc_report} chainOk={false} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Do not use: the audit log failed its check");
  });
});

describe("Verify ledger", () => {
  it("verifies the ledger and reports how far it checked and who signed the head", async () => {
    show(<VerifyPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Check audit log" }));
    expect(await screen.findByTestId("verify-result")).toHaveTextContent("The audit log passed its check");
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
  });

  it("names the first bad entry when the real ledger does not verify", async () => {
    server.use(
      http.post("/api/audit/verify", () =>
        HttpResponse.json({
          ok: false,
          checked_to_seq: 900,
          first_bad_seq: 702,
          signed_head_seq: null,
          notary: "UNSIGNED",
        }),
      ),
    );
    show(<VerifyPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Check audit log" }));
    expect(await screen.findByTestId("verify-result")).toHaveTextContent("The first bad entry is 702");
    expect(screen.getByText("Not confirmed")).toBeInTheDocument();
    expect(screen.getByText("None yet")).toBeInTheDocument();
  });

  it("tells the tamper demo apart from a real result and says the ledger was not changed", async () => {
    show(<VerifyPanel />, await api.login("admin_01", "demo"));
    fireEvent.click(screen.getByRole("button", { name: "Run tamper test" }));
    const demo = await screen.findByTestId("tamper-result");
    expect(demo).toHaveTextContent("The real audit log wasn't changed");
    expect(demo).toHaveTextContent(`The check fails at entry ${TAMPERED_SEQ}`);
    expect(screen.queryByTestId("verify-result")).not.toBeInTheDocument();
  });

  it("explains a rate limit and a missing route instead of failing silently", async () => {
    server.use(
      http.post("/api/audit/verify", () =>
        HttpResponse.json(
          { error: { code: "RATE_LIMITED", message: "verify again in 12 s" } },
          { status: 429 },
        ),
      ),
      http.post("/api/audit/tamper-demo", () => new HttpResponse(null, { status: 404 })),
    );
    show(<VerifyPanel />, await api.login("admin_01", "demo"));
    fireEvent.click(screen.getByRole("button", { name: "Check audit log" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("verify again in 12 s");
    fireEvent.click(screen.getByRole("button", { name: "Run tamper test" }));
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getAllByRole("alert")[1]).toHaveTextContent("isn't available yet");
  });
});

describe("After-action page", () => {
  it("opens on the clocks, reads the ledger state in one sentence and shows the exercise banner only in exercise mode", async () => {
    show(<AfterActionPage />);
    expect(await screen.findByTestId("review-sentence")).toHaveTextContent("The audit log passed its check");
    expect(screen.getAllByTestId("clock-row").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("exercise-banner")).not.toBeInTheDocument();
  });

  it("says the review is not available when the route is missing", async () => {
    server.use(http.get("/api/after-action", () => new HttpResponse(null, { status: 404 })));
    show(<AfterActionPage />);
    expect(await screen.findByText("The review isn't available yet.")).toBeInTheDocument();
  });

  it("shows the exercise banner when the scenario is an exercise", async () => {
    server.use(http.get("/api/scenario", () => HttpResponse.json({ ...scenario, mode: "EXERCISE" })));
    show(<AfterActionPage />);
    expect(await screen.findByTestId("exercise-banner")).toHaveTextContent("not for operational use");
  });
});
