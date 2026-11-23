import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { PrintBrief } from "./PrintBrief";

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.dataset.theme = "light";
});

describe("briefing print", () => {
  it("opens the browser's print dialog", () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    render(
      <TooltipProvider>
        <PrintBrief />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Print / Save as PDF" }));
    expect(print).toHaveBeenCalledOnce();
  });

  it("prints in the light theme and gives the reader's theme back afterwards", () => {
    document.documentElement.dataset.theme = "dark";
    window.dispatchEvent(new Event("beforeprint"));
    expect(document.documentElement.dataset.theme).toBe("light");
    window.dispatchEvent(new Event("beforeprint"));
    window.dispatchEvent(new Event("afterprint"));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
