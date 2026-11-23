import { mkdirSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SHOTS = process.env.SGW_SHOTS;

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function mapReady(page: Page) {
  await page.waitForFunction(() =>
    Boolean((window as unknown as { __sgwMap?: { loaded(): boolean } }).__sgwMap?.loaded()),
  );
}

async function sourceCount(page: Page, source: string): Promise<number> {
  return page.evaluate(
    (id) =>
      (
        window as unknown as { __sgwMap: { querySourceFeatures(s: string): unknown[] } }
      ).__sgwMap.querySourceFeatures(id).length,
    source,
  );
}

async function gustTotal(page: Page): Promise<number> {
  const texts = await page.getByTestId("station-value").allTextContents();
  return texts.reduce((sum, t) => sum + Number.parseInt(t, 10), 0);
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

test("map observed layers: off by default, toggles, gust labels without collisions, gated by the history bar", async ({
  page,
}) => {
  const errors = watchConsole(page);
  await page.setViewportSize({ width: 1288, height: 742 });
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);

  await page.getByTestId("layer-toggle").click();
  const panel = page.getByTestId("layer-panel");
  const observed = panel.getByRole("region", { name: "Observed" });
  for (const name of ["Warnings", "River gauges", "Airport wind"])
    await expect(observed.getByRole("switch", { name })).not.toBeChecked();
  await expect(page.getByTestId("wind-station")).toHaveCount(0);

  const live = page.waitForRequest((r) => r.url().includes("/api/hazard/observed?as_of="));
  for (const name of ["Warnings", "River gauges", "Airport wind"])
    await observed.getByRole("switch", { name }).click();
  await live;
  await expect(page.getByTestId("wind-station")).toHaveCount(6);
  await expect(page.getByTestId("station-value").first()).toContainText("mph");
  await expect.poll(() => sourceCount(page, "warnings")).toBeGreaterThan(0);
  await expect.poll(() => sourceCount(page, "gauges")).toBeGreaterThan(0);

  const legend = page.getByTestId("map-legend");
  await page.getByTestId("legend-toggle").click();
  await expect(page.getByTestId("layer-panel")).toHaveCount(0);
  await expect(legend).toContainText("River gauges");
  await expect(legend).toContainText("Airport wind");
  await expect(legend).toContainText("Warnings");
  await expect(legend.getByRole("switch")).toHaveCount(0);
  await page.getByTestId("layer-toggle").click();

  const boxes = await page
    .getByTestId("station-value")
    .evaluateAll((els) =>
      els.map((e) => e.getBoundingClientRect()).map((r) => [r.left, r.top, r.right, r.bottom]),
    );
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) {
      const [a, b] = [boxes[i] as number[], boxes[j] as number[]];
      const overlap =
        (a[0] as number) < (b[2] as number) &&
        (b[0] as number) < (a[2] as number) &&
        (a[1] as number) < (b[3] as number) &&
        (b[1] as number) < (a[3] as number);
      expect(overlap).toBe(false);
    }

  await page.getByTestId("wind-station").first().hover();
  await expect(page.getByTestId("map-tip")).toContainText("airport");
  await expect(page.getByTestId("map-tip")).toContainText("mph");
  await shot(page, "map-observed-live");

  const liveGusts = await gustTotal(page);
  const slider = page.getByRole("slider", { name: "Advisory history" });
  const early = page.waitForRequest((r) => r.url().includes("as_of=2024-09-24T15%3A00%3A00Z"));
  await slider.focus();
  await page.keyboard.press("Home");
  await early;
  await expect.poll(() => sourceCount(page, "warnings")).toBe(0);
  await expect.poll(() => gustTotal(page)).toBeLessThan(liveGusts);
  await shot(page, "map-observed-first-advisory");

  await panel.getByRole("switch", { name: "Airport gust values" }).click();
  await expect(page.getByTestId("station-value")).toHaveCount(0);
  await expect(page.getByTestId("wind-station")).toHaveCount(6);
  await observed.getByRole("switch", { name: "Airport wind" }).click();
  await expect(page.getByTestId("wind-station")).toHaveCount(0);
  await expect(panel.getByRole("switch", { name: "Airport gust values" })).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("after-action: What happened lists the declarations and the most severe storm reports", async ({
  page,
}) => {
  const errors = watchConsole(page);
  await login(page, USER.auditor);
  await page.goto("/after-action");
  const section = page.getByTestId("what-happened");
  await expect(section).toBeVisible();
  await expect(section.getByTestId("declaration-row")).toHaveCount(2);
  await expect(section.getByRole("link", { name: "DR-4830-GA" })).toHaveAttribute(
    "href",
    "https://www.fema.gov/disaster/4830",
  );
  await expect(section.getByTestId("storm-event-row")).toHaveCount(5);
  await expect(section).toContainText("not endorsed by FEMA");
  await shot(page, "after-action-what-happened");
  expect(errors).toEqual([]);
});
