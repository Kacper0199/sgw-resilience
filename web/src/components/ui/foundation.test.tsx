import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { DomainMark } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

describe("Button", () => {
  it("is a rounded rectangle, never a pill", () => {
    render(
      <>
        <Button>Sign</Button>
        <Button size="sm">Small</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Sign" }).className).toContain("rounded-md");
    expect(screen.getByRole("button", { name: "Small" }).className).toContain("rounded-[7px]");
    expect(screen.getByRole("button", { name: "Sign" }).className).not.toContain("rounded-full");
  });
});

describe("DomainMark", () => {
  it("is an 8 px square with the domain name, not an icon", () => {
    const { container } = render(<DomainMark domain="water" />);
    expect(screen.getByRole("img", { name: "Water" }).className).toContain("size-2");
    expect(container.querySelector("svg")).toBeNull();
  });
});

describe("Tabs", () => {
  it("marks a tab as pointer-focused on click and clears it on keyboard use", () => {
    render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">One</TabsTrigger>
          <TabsTrigger value="b">Two</TabsTrigger>
        </TabsList>
      </Tabs>,
    );
    const one = screen.getByRole("tab", { name: "One" });
    fireEvent.pointerDown(one);
    expect(one).toHaveAttribute("data-pointer");
    fireEvent.keyDown(one, { key: "ArrowRight" });
    expect(one).not.toHaveAttribute("data-pointer");
  });
});

function Opener() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open it
      </button>
      {open && (
        <Dialog open onOpenChange={(o) => !o && setOpen(false)}>
          <DialogContent>
            <DialogTitle>Sign decision</DialogTitle>
            <button type="button">Approve alone…</button>
            <button type="button" data-autofocus>
              Sign
            </button>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

describe("Dialog focus", () => {
  it("starts on the safe button and returns to the opener on Escape", async () => {
    render(<Opener />);
    const opener = screen.getByRole("button", { name: "Open it" });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign" })).toHaveFocus());
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Open it" })).toHaveFocus());
  });
});
