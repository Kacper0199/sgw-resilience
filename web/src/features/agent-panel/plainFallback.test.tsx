import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnswerBody } from "./AnswerBody";
import { parseAnswer } from "./parseAnswer";

const PLAIN = [
  "Answer from platform data. The recorded AI answer no longer matches the current state.",
  "[DC-D3-PS17-FUEL] DC-D3-PS17-FUEL: missed, not signed by its deadline.",
  '[quote] The procedure says: "Revise a published ETR when the P50 moves by more than 12 h." [1]',
  '[1] DOM 14.206 Rev K, 6.0 PROCEDURE, pp. 1-3: "Revise a published ETR when the P50 moves by more than 12 h."',
].join("\n");

describe("the plain fallback answer", () => {
  it("says why the AI did not write it and puts the source badge on its row, once", () => {
    const parsed = parseAnswer(PLAIN);
    expect(parsed.kind).toBe("m2");
    render(
      <AnswerBody
        parsed={parsed}
        reason="llm_unavailable"
        tainted={false}
        activeN={null}
        onSelect={() => {}}
      />,
    );
    const box = screen.getByTestId("findings-only");
    expect(box).toHaveTextContent("Answer from platform data");
    expect(screen.getByTestId("fallback-why")).toHaveTextContent(
      "The recorded AI answer no longer matches the current state.",
    );
    expect(screen.getAllByTestId("source-badge")).toHaveLength(1);
    expect(box).not.toHaveTextContent("Evidence gathered");
    expect(box).not.toHaveTextContent("[1]");
  });
});
