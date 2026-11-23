import { HttpResponse, http } from "msw";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { server } from "@/mocks/server";
import { ApiError, api, setUnauthorizedHandler } from "./api";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  setUnauthorizedHandler(null);
});

describe("api errors", () => {
  it("turns a non-JSON error body into an ApiError", async () => {
    server.use(http.get("/api/me", () => new HttpResponse("<html>bad gateway</html>", { status: 502 })));
    const err = await api.me().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(502);
  });

  it("does not sign the person out when the step-up password is wrong", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    server.use(
      http.post("/api/auth/step-up", () =>
        HttpResponse.json(
          { error: { code: "STEP_UP_FAILED", message: "password did not match" } },
          { status: 401 },
        ),
      ),
    );
    await expect(api.stepUp("nope")).rejects.toMatchObject({ code: "STEP_UP_FAILED" });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("still signs the person out on any other 401", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    server.use(
      http.get("/api/me", () =>
        HttpResponse.json({ error: { code: "UNAUTHENTICATED", message: "x" } }, { status: 401 }),
      ),
    );
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});

describe("api reads", () => {
  it("revalidates every read with the server instead of reusing a cached body", async () => {
    server.use(
      http.get("/api/water/advisories", () =>
        HttpResponse.json({ as_of: "2024-09-27T12:00:00Z", advisories: [] }),
      ),
    );
    const spy = vi.spyOn(globalThis, "fetch");
    const { get } = await import("./api");
    await get("/api/water/advisories");
    expect(spy.mock.calls[0]?.[1]).toMatchObject({ cache: "no-cache" });
    spy.mockRestore();
  });
});
