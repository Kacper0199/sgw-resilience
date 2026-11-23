import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useListed } from "./useQueue";

function listed(id: string | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(["proposals"], [{ proposal_id: "PRP-NOW" }]);
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(() => useListed(id), { wrapper }).result.current;
}

describe("open decision after a load", () => {
  it("is read only while the decision list holds it", () => {
    expect(listed("PRP-NOW")).toEqual({ id: "PRP-NOW", gone: false });
    expect(listed("PRP-OLD-SCENARIO")).toEqual({ id: null, gone: true });
    expect(listed(null)).toEqual({ id: null, gone: false });
  });
});
