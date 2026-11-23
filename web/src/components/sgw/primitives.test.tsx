import { fireEvent, render, screen, within } from "@testing-library/react";
import { Inbox } from "lucide-react";
import { MemoryRouter } from "react-router";
import { GLOSSARY } from "@/content/glossary";
import { UI_SEVERITY } from "@/contracts/vocab.gen";
import {
  ClockText,
  Container,
  CountTabs,
  EmptyState,
  InfoTip,
  KeyFacts,
  SeverityGlyph,
  SourceLine,
  StatusIndicator,
  TierBadge,
} from ".";

const wrap = (ui: React.ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("glossary", () => {
  it("keeps every toggletip text within 25 words", () => {
    for (const [key, entry] of Object.entries(GLOSSARY)) {
      const words = entry.text.split(/\s+/).length;
      expect(words, key).toBeLessThanOrEqual(25);
    }
  });
});

describe("InfoTip", () => {
  it("opens on click, offers Help and closes on Escape", () => {
    wrap(<InfoTip term="decide_by" />);
    fireEvent.click(screen.getByRole("button", { name: 'What does "Decide by" mean?' }));
    expect(screen.getByText(/Latest time to decide/)).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Decide by" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "More in Help" })).toHaveAttribute("href", "/help#decide_by");
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.queryByText(/Latest time to decide/)).not.toBeInTheDocument();
  });
});

describe("Container", () => {
  it("renders a labelled region with title, count and actions", () => {
    wrap(
      <Container title="Decisions" info="queue" count={7} actions={<button type="button">Filter</button>}>
        body
      </Container>,
    );
    const region = screen.getByRole("region", { name: "Decisions" });
    expect(within(region).getByText("7")).toBeInTheDocument();
    expect(within(region).getByRole("button", { name: "Filter" })).toBeInTheDocument();
  });
});

const Boom = () => {
  throw new Error("map exploded");
};

describe("Container failure isolation", () => {
  it("keeps a crashing child inside its container", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    wrap(
      <>
        <Container title="Map">
          <Boom />
        </Container>
        <Container title="Queue">still here</Container>
      </>,
    );
    quiet.mockRestore();
    expect(within(screen.getByRole("region", { name: "Map" })).getByRole("alert")).toHaveTextContent(
      "Couldn't load this section.",
    );
    expect(screen.getByRole("region", { name: "Queue" })).toHaveTextContent("still here");
  });
});

describe("KeyFacts and CountTabs", () => {
  it("lists key-value pairs", () => {
    wrap(
      <KeyFacts
        facts={[
          { label: "Severity", value: "Severe" },
          { label: "Approval", value: "2 teams sign" },
        ]}
      />,
    );
    expect(screen.getByText("Severity").closest("div")).toHaveTextContent("Severe");
  });
  it("shows counts in tab labels", () => {
    wrap(
      <CountTabs
        label="Decision detail"
        tabs={[
          { value: "basis", label: "Basis", content: "b" },
          { value: "evidence", label: "Evidence", count: 4, content: "e" },
        ]}
      />,
    );
    expect(screen.getByRole("tab", { name: /Evidence/ })).toHaveTextContent("4");
  });
});

describe("severity, status, tier", () => {
  it("renders a word for every severity so colour is never the only signal", () => {
    for (const level of UI_SEVERITY) {
      const { container, unmount } = render(<SeverityGlyph level={level} />);
      expect(container.querySelector("svg")).not.toBeNull();
      expect(container.textContent?.length).toBeGreaterThan(3);
      unmount();
    }
  });
  it("renders status text beside its glyph", () => {
    render(<StatusIndicator status="waiting_approval" />);
    expect(screen.getByText("Waiting for sign-off")).toBeInTheDocument();
  });
  it("opens the tier definition from the badge", () => {
    wrap(<TierBadge tier="T3" />);
    fireEvent.click(screen.getByRole("button", { name: /Approval: 2 teams sign/ }));
    expect(screen.getByText(/Two approvers from two different teams/)).toBeInTheDocument();
  });
});

describe("ClockText", () => {
  it("shows relative and absolute time and marks missed deadlines", () => {
    const { container } = render(<ClockText at="2024-09-27T04:10:00Z" now="2024-09-27T01:00:00Z" />);
    expect(container).toHaveTextContent("in 3 h 10 m");
    expect(container).toHaveTextContent("00:10 ET (04:10Z)");
    const { container: late } = render(<ClockText at="2024-09-27T00:00:00Z" now="2024-09-27T01:00:00Z" />);
    expect(late.querySelector(".text-crit")).not.toBeNull();
  });
});

describe("EmptyState and SourceLine", () => {
  it("shows one icon, one line and one action", () => {
    render(
      <EmptyState
        icon={Inbox}
        title="Nothing waiting on you"
        action={<button type="button">Show all</button>}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Nothing waiting on you");
    expect(screen.getByRole("button", { name: "Show all" })).toBeInTheDocument();
  });
  it("renders a muted source", () => {
    render(<SourceLine>Model OUT-2, synthetic input</SourceLine>);
    expect(screen.getByText("Model OUT-2, synthetic input")).toBeInTheDocument();
  });
});
