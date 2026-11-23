import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

const proposals = [
  { proposal_id: "PRP-ZR-F2671161857D", title: "Dispatch the fuel truck to PS-17" },
  { proposal_id: "PRP-6A1B2C3D4E5F6A7B", title: "Hook up the portable generator at PS-17" },
  { proposal_id: "PRP-CREW-AIK-0926A", title: "Pre-position crews at Sandhill and Millpond yards" },
];

vi.mock("@/lib/api", () => ({ api: { proposals: () => Promise.resolve(proposals) } }));
vi.mock("@/auth/useSession", () => ({ useLogout: () => ({ mutate: vi.fn() }) }));
vi.mock("./useNavModules", () => ({ useNavModules: () => [] }));
vi.mock("./useTheme", () => ({ useTheme: () => ["light", vi.fn()] }));

describe("CommandPalette search", () => {
  it("finds every decision that names the typed station", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CommandPalette open onOpenChange={vi.fn()} onToggleSidebar={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("Hook up the portable generator at PS-17");
    fireEvent.change(screen.getByPlaceholderText("Jump to decision or command"), {
      target: { value: "PS-17" },
    });
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Dispatch the fuel truck to PS-17", "Hook up the portable generator at PS-17"]);
  });
});
