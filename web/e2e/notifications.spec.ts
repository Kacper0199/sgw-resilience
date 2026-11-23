import { expect, type Page, test } from "@playwright/test";
import { login, switchUser, USER } from "./support/login";

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const nav = (page: Page) => page.getByRole("navigation", { name: "Main menu" }).first();

test("notifications: the unread count sits in the nav, an item opens its page and is then read", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.commander);
  const entry = nav(page).getByRole("link", { name: /Notifications/ });
  await expect(entry).toContainText(/\d/);
  await entry.click();
  await expect(page).toHaveURL(/\/notifications$/);
  const items = page.getByTestId("notification");
  await expect(items.first()).toBeVisible();
  const unread = await page.locator('[data-testid="notification"][data-read="false"]').count();
  expect(unread).toBeGreaterThan(1);
  await items.filter({ hasText: "Decision waiting on you" }).click();
  await expect(page).toHaveURL(/\/decisions\/PRP-/);
  await page.goBack();
  await expect(page.locator('[data-testid="notification"][data-read="false"]')).toHaveCount(unread - 1);
  await page.getByRole("button", { name: "Mark all read" }).click();
  await expect(page.locator('[data-testid="notification"][data-read="false"]')).toHaveCount(0);
  await expect(entry).not.toContainText(/\d/);
  expect(errors).toEqual([]);
});

test("permissions: stop controls and Admin only for those the API accepts", async ({ page }) => {
  await login(page, USER.waterCompliance);
  await expect(nav(page).getByRole("link", { name: "Notifications" })).toBeVisible();
  await expect(nav(page).getByRole("link", { name: "Admin" })).toHaveCount(0);
  await page.goto("/health?tab=safety");
  await expect(page.getByTestId("mode-row").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Raise stop level" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Set mode" })).toHaveCount(0);

  await switchUser(page, USER.commander);
  await page.goto("/health?tab=safety");
  await expect(page.getByRole("button", { name: "Raise stop level" })).toBeVisible();

  await switchUser(page, USER.admin);
  await expect(nav(page).getByRole("link", { name: "Admin" })).toBeVisible();
});

test("actions: the data owner loads a dataset now and stops a run that waits for sign-off", async ({
  page,
}) => {
  await login(page, USER.dataOwner);
  await page.goto("/health?tab=data");
  await page
    .getByRole("button", { name: /^Load now: / })
    .first()
    .click();
  const dialog = page.getByTestId("run-now-dialog");
  await dialog.getByRole("button", { name: "Load now" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(/ loaded\.$/)).toBeVisible();

  await page.goto("/health?tab=runs");
  await page
    .getByRole("button", { name: /^Stop request/ })
    .first()
    .click();
  const reason = page.getByTestId("reason-dialog");
  await reason.getByLabel("Reason").fill("Waits for a sign-off nobody will give");
  await reason.getByRole("button", { name: "Stop request" }).click();
  await expect(reason).toBeHidden();
  await expect(page.getByText("Request stopped.")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Stop request/ })).toHaveCount(0);
});

test("map: the outage surge layer colours counties by start time, and the start times stay pinned while the map moves", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1288, height: 742 });
  await login(page, USER.dutyManager);
  await page.goto("/map");
  await page.waitForFunction(() =>
    Boolean((window as unknown as { __sgwMap?: { loaded(): boolean } }).__sgwMap?.loaded()),
  );
  await page.getByTestId("layer-toggle").click();
  await page.getByTestId("layer-panel").getByRole("switch", { name: "Outage surges" }).click();
  await page.getByRole("button", { name: "Collapse layers" }).click();
  await page.waitForFunction(() => {
    const map = (
      window as unknown as {
        __sgwMap: { getSource(id: string): { serialize(): { data: { features: unknown[] } } } };
      }
    ).__sgwMap;
    return (map.getSource("surges")?.serialize().data.features.length ?? 0) > 0;
  });
  const surgeStyle = await page.evaluate(() => {
    const map = (
      window as unknown as {
        __sgwMap: {
          getPaintProperty(layer: string, name: string): unknown;
          getFilter(layer: string): unknown;
        };
      }
    ).__sgwMap;
    return {
      fill: JSON.stringify(map.getPaintProperty("surges-fill", "fill-color")),
      outline: JSON.stringify(map.getFilter("surges-line")),
    };
  });
  expect(surgeStyle.fill, "counties are coloured by when the surge began").toMatch(/onset|#/);
  expect(surgeStyle.outline, "only the newest surges keep the outline").toContain("recent");
  await page.getByTestId("legend-toggle").click();
  await expect(page.getByTestId("map-legend")).toContainText("First surge at (ET)");
  await page.getByRole("button", { name: "Legend" }).click();
  const run = await page.evaluate(async () => {
    type M = {
      getSource(id: string): {
        serialize(): { data: { features: { geometry: { coordinates: number[][][] } }[] } };
      };
      getContainer(): HTMLElement;
      project(c: [number, number]): { x: number; y: number };
      on(e: string, f: () => void): void;
      off(e: string, f: () => void): void;
      once(e: string, f: () => void): void;
      jumpTo(o: object): void;
      easeTo(o: object): void;
      getCenter(): { lng: number; lat: number };
    };
    const map = (window as unknown as { __sgwMap: M }).__sgwMap;
    const ring = map.getSource("surges").serialize().data.features[0]?.geometry.coordinates[0] ?? [];
    const lon = ring.reduce((s, p) => s + (p[0] ?? 0), 0) / ring.length;
    const lat = ring.reduce((s, p) => s + (p[1] ?? 0), 0) / ring.length;
    await new Promise<void>((done) => {
      map.once("moveend", () => done());
      map.jumpTo({ center: [lon, lat], zoom: 8 });
    });
    await new Promise((r) => setTimeout(r, 400));
    let worst = 0;
    let samples = 0;
    const sample = () => {
      const host = map.getContainer().getBoundingClientRect();
      for (const el of document.querySelectorAll<HTMLElement>('[data-testid="surge-start"]')) {
        const [x, y, dx, dy] = (el.dataset.pin ?? "").split(",").map(Number);
        const r = el.getBoundingClientRect();
        if (r.width === 0) continue;
        const p = map.project([x as number, y as number]);
        worst = Math.max(
          worst,
          Math.hypot(
            r.left + r.width / 2 - (host.left + p.x + (dx as number)),
            r.top + r.height / 2 - (host.top + p.y + (dy as number)),
          ),
        );
        samples += 1;
      }
    };
    map.on("render", sample);
    const c = map.getCenter();
    await new Promise<void>((done) => {
      map.once("moveend", () => done());
      map.easeTo({ center: [c.lng + 0.15, c.lat - 0.1], duration: 700 });
    });
    map.off("render", sample);
    return { worst, samples };
  });
  expect(run.samples).toBeGreaterThan(10);
  expect(run.worst).toBeLessThan(2);
  await expect(page.getByTestId("surge-start").first()).toContainText(
    /^from [A-Z][a-z]{2} \d{1,2} \d{2}:\d{2} ET$/,
  );
});

test("briefing: one number for counties with an outage surge", async ({ page }) => {
  await login(page, USER.executive);
  await page.goto("/brief");
  await expect(page.getByTestId("surge-count")).toHaveText(/^\d+$/);
  await expect(page.getByTestId("surge-line")).toContainText("Outage surges");
});

test("decisions: the proposer withdraws an open decision with a reason", async ({ page }) => {
  await login(page, USER.dutyManager);
  await page.goto("/decisions/PRP-MUTUAL-AID");
  await page.getByRole("button", { name: "Withdraw…" }).click();
  const dialog = page.getByTestId("reason-dialog");
  await expect(dialog.getByRole("button", { name: "Withdraw" })).toBeDisabled();
  await dialog.getByLabel("Reason").fill("Superseded by the Millpond plan");
  await dialog.getByRole("button", { name: "Withdraw" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Decision withdrawn.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Withdraw…" })).toHaveCount(0);

  await switchUser(page, USER.executive);
  await page.goto("/decisions/PRP-AIK-STAGE");
  await expect(page.getByRole("heading", { level: 3 }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Withdraw/ })).toHaveCount(0);
});
