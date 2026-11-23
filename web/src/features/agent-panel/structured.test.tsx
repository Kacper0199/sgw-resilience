import { render, screen } from "@testing-library/react";
import { AnswerBody } from "./AnswerBody";
import type { Message } from "./api";
import { buildTurns } from "./buildTurns";
import type { ParsedAnswer } from "./types";

const message = (over: Partial<Message>): Message => ({
  message_id: "run-1.a",
  role: "assistant",
  text: "This is not in the documents.",
  created_at: "2024-09-28T18:00:00Z",
  ...over,
});

describe("structured answers from the server", () => {
  it("carries the path, the reason and the structured sources into the turn", () => {
    const turns = buildTurns(
      [
        message({ message_id: "run-1.u", role: "user", text: "When do I revise an ETR?" }),
        message({
          path: "llm",
          reason: null,
          citations: [
            {
              n: 1,
              citation_id: "DOM 14.206 Rev K",
              doc_id: "DOM-14-206",
              version: "K",
              section: "3.2",
              pages: "4",
              cited_text: "A global ETR is revised when",
              unverified: false,
            },
          ],
        }),
      ],
      new Map(),
    );
    expect(turns[0]?.answerPath).toBe("llm");
    expect(turns[0]?.citations).toEqual([
      {
        n: 1,
        citationId: "DOM 14.206 Rev K",
        section: "3.2",
        pages: "4",
        quote: "A global ETR is revised when",
        unverified: false,
      },
    ]);
  });

  it("says the assistant is unavailable instead of claiming the documents hold no answer", () => {
    const parsed: ParsedAnswer = {
      kind: "not_in_documents",
      body: "This is not in the documents.",
      lead: null,
      citations: [],
      platform: [],
    };
    render(
      <AnswerBody
        parsed={parsed}
        reason="llm_unavailable"
        tainted={false}
        activeN={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByTestId("unavailable")).toHaveTextContent("The assistant is not available");
    expect(screen.queryByTestId("abstain")).toBeNull();
  });

  it("keeps the not-in-documents notice when the model found nothing", () => {
    const parsed: ParsedAnswer = {
      kind: "not_in_documents",
      body: "This is not in the documents.",
      lead: null,
      citations: [],
      platform: [],
    };
    render(
      <AnswerBody
        parsed={parsed}
        reason="model_not_in_documents"
        tainted={false}
        activeN={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByTestId("abstain")).toBeInTheDocument();
  });
});
