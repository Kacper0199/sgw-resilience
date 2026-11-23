import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnswerBody } from "./AnswerBody";
import { parseAnswer } from "./parseAnswer";

const props = { tainted: false, activeN: null, onSelect: () => {} };

describe("an answer under a Polish question", () => {
  it("says the assistant is not available in Polish", () => {
    const parsed = parseAnswer("This is not in the documents.", "not_in_documents");
    render(
      <AnswerBody
        {...props}
        parsed={parsed}
        reason="llm_unavailable"
        question="Ilu klientów nie ma prądu?"
      />,
    );
    expect(screen.getByTestId("unavailable")).toHaveTextContent("Asystent jest niedostępny");
    expect(screen.getByTestId("unavailable")).not.toHaveTextContent("not available");
  });

  it("keeps the code answer's Polish lead as its title and reason", () => {
    const text = [
      "Odpowiedź z danych platformy. AI jest teraz niedostępne.",
      "[DC-D3-PS17-FUEL] DC-D3-PS17-FUEL: termin minął bez podpisu.",
    ].join("\n");
    render(
      <AnswerBody
        {...props}
        parsed={parseAnswer(text, "m2")}
        reason="llm_unavailable"
        question="Co z PS-17?"
      />,
    );
    expect(screen.getByTestId("findings-only")).toHaveTextContent("Odpowiedź z danych platformy");
    expect(screen.getByTestId("fallback-why")).toHaveTextContent("AI jest teraz niedostępne.");
  });

  it("stays English under an English question", () => {
    const parsed = parseAnswer("This is not in the documents.", "not_in_documents");
    render(
      <AnswerBody
        {...props}
        parsed={parsed}
        reason="llm_unavailable"
        question="How many customers are out?"
      />,
    );
    expect(screen.getByTestId("unavailable")).toHaveTextContent("The assistant is not available");
  });
});
