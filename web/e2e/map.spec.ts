import { mkdirSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const PS17 = "PRP-PS17-FDR2207-PRIO";
const STAGE = "PRP-AIK-STAGE";
const SHOTS = process.env.SGW_SHOTS;

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => {
    document.documentElement.dataset.theme = t;
  }, theme);
}

async function mapReady(page: Page) {
  await page.waitForFunction(() =>
    Boolean((window as unknown as { __sgwMap?: { loaded(): boolean } }).__sgwMap?.loaded()),
  );
  await page.waitForFunction(() => {
    try {
      return (window as unknown as { __sgwMap: { areTilesLoaded(): boolean } }).__sgwMap.areTilesLoaded();
    } catch {
      return false;
    }
  });
}

async function assetPixel(page: Page, lon: number, lat: number) {
  return page.evaluate(
    ([x, y]) => {
      const map = (
        window as unknown as {
          __sgwMap: {
            project(c: [number, number]): { x: number; y: number };
            getCanvas(): HTMLCanvasElement;
          };
        }
      ).__sgwMap;
      const p = map.project([x as number, y as number]);
      const r = map.getCanvas().getBoundingClientRect();
      return { x: r.left + p.x, y: r.top + p.y };
    },
    [lon, lat],
  );
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

test("map page: layer panel, grouped legend, advisory and lifelines", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto("/map");
  await expect(page.getByRole("heading", { name: "Map", exact: true, level: 1 })).toBeAttached();
  await mapReady(page);

  await expect(page.getByTestId("layer-panel")).toHaveCount(0);
  await expect(page.getByTestId("legend-toggle")).toBeVisible();
  await page.setViewportSize({ width: 1700, height: 900 });
  await page.getByTestId("layer-toggle").click();
  await page.getByTestId("legend-toggle").click();
  const legend = page.getByTestId("map-legend");
  await expect(legend).toContainText("Outage risk");
  await expect(legend).toContainText("Power asset");
  await expect(legend).toContainText("Storm cone");
  await expect(legend).toContainText("Storm track so far");
  await expect(legend).toContainText("Forecast track");
  await expect(legend).toContainText("Storm position now");
  await expect(legend.getByRole("switch")).toHaveCount(0);
  await expect(page.getByText("The cone shows where the storm's center may go")).toHaveCount(0);

  const panel = page.getByTestId("layer-panel");
  await panel.getByRole("switch", { name: "Peak gust", exact: true }).click();
  await expect(legend).toContainText("Peak gust");
  await expect(legend).toContainText("mph");
  await panel.getByRole("radio", { name: "Water" }).click();
  await expect(legend).not.toContainText("Power asset");
  await expect(legend).toContainText("Water asset");

  const lifelines = page.getByTestId("lifelines");
  await expect(lifelines).toContainText("Water pump stations");
  await expect(lifelines).toContainText("PS-17");
  await expect(lifelines.getByText("In high-risk counties")).toBeVisible();
  await expect(page.getByTestId("riskiest-counties")).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("map page: a selected decision draws the numbered chain to the hospital", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  await expect(page.getByTestId("chain-stop").first()).toHaveAttribute("aria-label", /^Step 1: /);
  await expect(page.getByTestId("chain-stop").last()).toHaveAttribute("aria-label", /^Step 5: /);
  await expect(page.getByTestId("map-selection")).toContainText("Restore feeder 2207 first");
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(page.getByTestId("chain-stop")).toHaveCount(0);
  await expect(page.getByTestId("map-selection")).toHaveCount(0);
  await page.goto(`/map?d=${PS17}`);
  await page.getByRole("link", { name: "View decision" }).click();
  await expect(page).toHaveURL(new RegExp(`d=${PS17}`));
  expect(errors).toEqual([]);
});

test("decisions home: the row pans the map, the map click selects the most urgent decision on that asset, the queue is never filtered", async ({
  page,
}) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto(`/?d=${STAGE}`);
  await mapReady(page);
  const rows = page.getByTestId("decision-row");
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();

  const row = page.getByTestId("decision-row").filter({ hasText: "feeder 2207" });
  await row.click();
  await expect(page).toHaveURL(new RegExp(`d=${PS17}`));
  await expect(page.getByTestId("chain-stop").first()).toBeVisible();

  await page.getByTestId("decision-row").filter({ hasText: "Aiken yard" }).click();
  await expect(page).toHaveURL(new RegExp(`d=${STAGE}`));
  await page.waitForTimeout(800);
  const target = await assetPixel(page, -81.719, 33.564);
  await page.mouse.click(target.x, target.y);
  await expect(page).toHaveURL(/d=PRP-PS17-FUEL/);
  await expect(rows).toHaveCount(before);
  expect(errors).toEqual([]);
});

test("map page: a click on an asset opens the side panel with its open decisions", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  await page.waitForTimeout(800);
  const target = await assetPixel(page, -81.719, 33.564);
  await page.mouse.click(target.x, target.y);
  const panel = page.getByTestId("asset-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Open decisions here" })).toBeVisible();
  await expect(panel.getByRole("link", { name: "View decision" }).first()).toBeVisible();
  await panel.getByRole("button", { name: "Close details" }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId("lifelines")).toBeVisible();
  expect(errors).toEqual([]);
});

test("map: no serious accessibility violations in light and dark", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await page.waitForTimeout(400);
    const result = await new AxeBuilder({ page }).analyze();
    const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(
      serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`),
      theme,
    ).toEqual([]);
  }
});

test("map: screenshots for the review", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, USER.commander);
  for (const [w, h] of [
    [1440, 900],
    [1920, 1080],
  ] as const) {
    await page.setViewportSize({ width: w, height: h });
    for (const theme of ["light", "dark"] as const) {
      await page.goto("/map");
      await mapReady(page);
      await setTheme(page, theme);
      await page.waitForTimeout(700);
      await shot(page, `map-overview-${w}-${theme}`);
      await page.goto(`/map?d=${PS17}`);
      await mapReady(page);
      await setTheme(page, theme);
      await page.waitForTimeout(700);
      await shot(page, `map-${w}-${theme}`);
      await page.goto(`/?d=${PS17}`);
      await mapReady(page);
      await setTheme(page, theme);
      await page.waitForTimeout(700);
      await shot(page, `home-map-${w}-${theme}`);
    }
  }
  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  await page.evaluate(() => {
    document.documentElement.style.filter = "grayscale(1)";
  });
  await page.waitForTimeout(500);
  await shot(page, "map-1920-grayscale");
  await page.evaluate(() => {
    document.documentElement.style.filter = "";
  });
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/map");
  await mapReady(page);
  await page.waitForTimeout(500);
  await shot(page, "map-1024-light");
});

test("map: reduced motion still selects and draws the chain without errors", async ({ browser }) => {
  const context = await browser.newContext({
    reducedMotion: "reduce",
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto(`/?d=${STAGE}`);
  await mapReady(page);
  await page.getByTestId("decision-row").filter({ hasText: "feeder 2207" }).click();
  await expect(page.getByTestId("chain-stop").first()).toBeVisible();
  expect(errors).toEqual([]);
  await context.close();
});

type TestMap = {
  getZoom(): number;
  getCenter(): { lng: number; lat: number };
  jumpTo(o: { zoom?: number; center?: [number, number] }): void;
  project(c: [number, number]): { x: number; y: number };
  unproject(p: [number, number]): { lng: number; lat: number };
  queryRenderedFeatures(p: [number, number], o: { layers: string[] }): unknown[];
  getFilter(id: string): unknown;
  getSource(id: string): { serialize(): { data: { features: unknown[] } } };
  getContainer(): HTMLElement;
  resize(): void;
};

const settle = (page: Page) =>
  page.evaluate(
    () =>
      new Promise<void>((done) => {
        const map = (window as unknown as { __sgwMap: { once(e: string, f: () => void): void } }).__sgwMap;
        map.once("idle", () => done());
        setTimeout(done, 2500);
      }),
  );

test("map: zoom and pan stay inside the region", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  const limits = await page.evaluate(() => {
    const map = (window as unknown as { __sgwMap: TestMap }).__sgwMap;
    map.jumpTo({ zoom: 0.5 });
    const out = map.getZoom();
    map.jumpTo({ zoom: 18 });
    const inn = map.getZoom();
    map.jumpTo({ zoom: 6, center: [10, 60] });
    return { out, inn, center: map.getCenter() };
  });
  expect(limits.out).toBeGreaterThanOrEqual(3);
  expect(limits.inn).toBeLessThanOrEqual(10);
  expect(limits.center.lng).toBeLessThanOrEqual(-60);
  expect(limits.center.lat).toBeLessThanOrEqual(47);
});

test("map: the storm cone is one polygon and renders the same at every zoom", async ({ page }) => {
  test.setTimeout(90_000);
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  await page.getByTestId("history-stop").nth(8).click();
  await expect(page.getByRole("slider", { name: "Advisory history" })).toHaveAttribute(
    "aria-valuetext",
    /Sep 26 11:00 ET advisory/,
  );
  await settle(page);
  const result = await page.evaluate(async () => {
    const map = (window as unknown as { __sgwMap: TestMap }).__sgwMap;
    const products = (await (await fetch("/geo/helene-nhc.json")).json()) as Record<
      string,
      { label: string; cone: [number, number][] }
    >;
    const ring = Object.values(products).find((p) => p.label === "N+1")?.cone ?? [];
    const inside = (x: number, y: number) => {
      let on = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i] as [number, number];
        const [xj, yj] = ring[j] as [number, number];
        if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) on = !on;
      }
      return on;
    };
    const lons = ring.map((p) => p[0]);
    const lats = ring.map((p) => p[1]);
    const center: [number, number] = [
      (Math.min(...lons) + Math.max(...lons)) / 2,
      (Math.min(...lats) + Math.max(...lats)) / 2,
    ];
    const features = map.getSource("cone").serialize().data.features.length;
    const rows: { zoom: number; checked: number; wrong: number }[] = [];
    for (const zoom of [3.2, 4, 5, 6, 7, 8, 9, 10]) {
      map.jumpTo({ zoom, center });
      await new Promise<void>((done) => {
        (map as unknown as { once(e: string, f: () => void): void }).once("idle", () => done());
        setTimeout(done, 2500);
      });
      const box = map.getContainer().getBoundingClientRect();
      let checked = 0;
      let wrong = 0;
      for (let ix = 1; ix < 18; ix++)
        for (let iy = 1; iy < 12; iy++) {
          const px: [number, number] = [(box.width * ix) / 18, (box.height * iy) / 12];
          const ll = map.unproject(px);
          const back = map.project([ll.lng, ll.lat]);
          const eps = 0.0001;
          const near = [
            [eps, 0],
            [-eps, 0],
            [0, eps],
            [0, -eps],
          ].some(
            ([dx, dy]) =>
              inside(ll.lng + (dx as number) * 40, ll.lat + (dy as number) * 40) !== inside(ll.lng, ll.lat),
          );
          if (near || Math.abs(back.x - px[0]) > 1) continue;
          checked++;
          const drawn = map.queryRenderedFeatures(px, { layers: ["cone-fill"] }).length > 0;
          if (drawn !== inside(ll.lng, ll.lat)) wrong++;
        }
      rows.push({ zoom, checked, wrong });
    }
    return { features, rows };
  });
  expect(result.features).toBe(1);
  for (const r of result.rows) {
    expect(r.checked, `zoom ${r.zoom}`).toBeGreaterThan(20);
    expect(r.wrong, `zoom ${r.zoom}`).toBe(0);
  }
});

test("map: hovering a county shows its value beside the cursor and outlines it", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  await page.waitForTimeout(900);
  const at = await page.evaluate(() => {
    const map = (
      window as unknown as {
        __sgwMap: TestMap & {
          queryRenderedFeatures(p: [number, number], o: { layers: string[] }): unknown[];
        };
      }
    ).__sgwMap;
    const box = map.getContainer().getBoundingClientRect();
    for (let x = box.width * 0.45; x < box.width * 0.95; x += 17)
      for (let y = box.height * 0.1; y < box.height * 0.9; y += 17) {
        const at: [number, number] = [x, y];
        const county = map.queryRenderedFeatures(at, { layers: ["county-fill"] }).length > 0;
        const asset =
          map.queryRenderedFeatures([x - 12, y - 12] as [number, number], { layers: ["electric"] }).length +
            map.queryRenderedFeatures(at, { layers: ["electric", "water-assets"] }).length >
          0;
        if (county && !asset) return { x: box.left + x, y: box.top + y };
      }
    return { x: 0, y: 0 };
  });
  await page.mouse.move(at.x, at.y);
  const tip = page.getByTestId("map-tip");
  await expect(tip).toBeVisible();
  await expect(tip).toContainText(/: \d+%/);
  const box = await tip.boundingBox();
  expect(Math.abs((box?.x ?? 0) - at.x)).toBeLessThan(40);
  const filter = await page.evaluate(() =>
    JSON.stringify((window as unknown as { __sgwMap: TestMap }).__sgwMap.getFilter("county-hover-line")),
  );
  expect(filter).not.toContain('""');
  await page.mouse.move(5, 5);
  await expect(tip).toHaveCount(0);
});

test("map: Open map from a decision opens zoomed on its assets and steps", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto(`/?d=${PS17}`);
  await page.getByRole("link", { name: "Open map" }).click();
  await expect(page).toHaveURL(new RegExp(`/map\\?d=${PS17}`));
  await mapReady(page);
  await expect(page.getByTestId("chain-stop").first()).toBeVisible();
  await page.waitForTimeout(900);
  const zoom = await page.evaluate(() => (window as unknown as { __sgwMap: TestMap }).__sgwMap.getZoom());
  expect(zoom).toBeGreaterThan(7);
  for (const stop of await page.getByTestId("chain-stop").all()) await expect(stop).toBeInViewport();
});

test("map: step markers are clickable, large and show their name on one line", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  await page.waitForTimeout(900);
  const stops = page.getByTestId("chain-stop");
  const box = await stops.first().boundingBox();
  expect(box?.width).toBeGreaterThanOrEqual(24);
  await stops.nth(1).hover();
  const tip = page.getByTestId("map-tip");
  await expect(tip).toContainText("2. ");
  const lines = await tip.evaluate((el) => getComputedStyle(el).whiteSpace);
  expect(lines).toBe("nowrap");
  await stops.nth(1).click();
  await expect(page.getByTestId("map-step")).toContainText("Step 2");
  await expect(page.getByTestId("asset-panel")).toBeVisible();
  const boxes = await stops.evaluateAll((els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    }),
  );
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i] as (typeof boxes)[number];
      const b = boxes[j] as (typeof boxes)[number];
      const apart = Math.hypot(a.x + a.w / 2 - (b.x + b.w / 2), a.y + a.h / 2 - (b.y + b.h / 2)) >= a.w;
      expect(apart, `step ${i + 1} and ${j + 1}`).toBe(true);
    }
});

test("map: ?asset= focuses and pulses the asset, ?county= outlines and frames the county", async ({
  page,
}) => {
  await login(page, USER.commander);
  await page.goto("/map?asset=PS-17");
  await mapReady(page);
  await expect(page.getByTestId("asset-panel")).toBeVisible();
  await expect(page.getByTestId("selected-pulse")).toHaveCount(1);
  await page.waitForTimeout(900);
  const zoom = await page.evaluate(() => (window as unknown as { __sgwMap: TestMap }).__sgwMap.getZoom());
  expect(zoom).toBeGreaterThan(7.5);

  await page.goto("/map?county=45003");
  await mapReady(page);
  await page.waitForTimeout(900);
  const view = await page.evaluate(() => {
    const map = (window as unknown as { __sgwMap: TestMap }).__sgwMap;
    return { zoom: map.getZoom(), filter: JSON.stringify(map.getFilter("county-focus-line")) };
  });
  expect(view.zoom).toBeGreaterThan(6.5);
  expect(view.filter).toContain("45003");
});

test("map: the pulse loops while an asset is selected and stands still with reduced motion", async ({
  browser,
}) => {
  for (const reduced of [false, true]) {
    const context = await browser.newContext({
      reducedMotion: reduced ? "reduce" : "no-preference",
      viewport: { width: 1440, height: 900 },
    });
    const page = await context.newPage();
    await login(page, USER.commander);
    await page.goto("/map?asset=PS-17");
    await mapReady(page);
    const pulse = page.getByTestId("selected-pulse");
    await expect(pulse).toHaveCount(1);
    const style = await pulse.evaluate((el) => {
      const s = getComputedStyle(el);
      return { name: s.animationName, count: s.animationIterationCount };
    });
    if (reduced) expect(style.name).toBe("none");
    else expect(style).toEqual({ name: "map-pulse", count: "infinite" });
    await context.close();
  }
});

test("map: the canvas follows its container when the panel resizes", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  const sizes = await page.evaluate(async () => {
    const map = (window as unknown as { __sgwMap: TestMap }).__sgwMap;
    const host = map.getContainer().closest("section") as HTMLElement;
    const canvas = map.getContainer().querySelector("canvas") as HTMLCanvasElement;
    const out: { host: number; canvas: number }[] = [];
    for (const w of [900, 600, 760]) {
      host.style.width = `${w}px`;
      await new Promise((r) => setTimeout(r, 300));
      out.push({ host: host.clientWidth, canvas: canvas.clientWidth });
    }
    return out;
  });
  for (const s of sizes) expect(Math.abs(s.host - s.canvas)).toBeLessThanOrEqual(1);
});

test("map: the history bar goes back by advisory, plays forward and returns to live", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  const bar = page.getByTestId("history-bar");
  const slider = bar.getByRole("slider", { name: "Advisory history" });
  await expect(bar).not.toContainText("N+1");
  await expect(slider).toHaveAttribute("aria-valuetext", /live/);
  const last = Number(await slider.getAttribute("aria-valuenow"));

  await bar
    .getByTestId("history-stop")
    .nth(last - 2)
    .click();
  await expect(page).toHaveURL(/at=2024-09-/);
  await expect(bar.getByRole("button", { name: "Back to live" })).toBeVisible();
  await expect(slider).not.toHaveAttribute("aria-valuetext", /live/);

  await slider.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(slider).toHaveAttribute("aria-valuenow", String(last - 3));
  await page.keyboard.press("End");
  await expect(slider).toHaveAttribute("aria-valuetext", /live/);
  await expect(page).not.toHaveURL(/at=/);

  await page.keyboard.press("Home");
  await bar.getByRole("button", { name: "Play advisories" }).click();
  await expect(slider).toHaveAttribute("aria-valuenow", "1", { timeout: 5000 });
  await bar.getByRole("button", { name: "Back to live" }).click();
  await expect(slider).toHaveAttribute("aria-valuetext", /live/);
  await expect(bar.getByRole("button", { name: "Play advisories" })).toBeVisible();
});

test("map: ?at= opens an earlier advisory and leaves the shared clock alone", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  const clock = (await page.getByTestId("top-band").textContent())?.match(/\d\d:\d\d ET/)?.[0];
  await page.goto("/map?at=2024-09-25T15:00:00Z");
  await mapReady(page);
  await expect(page.getByRole("button", { name: "Back to live" })).toBeVisible();
  await expect(page.getByTestId("top-band")).toContainText(clock ?? "never");
});

type SequenceStep = { number: number; title: string };

async function sequenceOnDecision(page: Page, id: string): Promise<SequenceStep[]> {
  await page.goto(`/?d=${id}`);
  await page.getByRole("tab", { name: /Sequence/ }).click();
  const rows = await page.getByTestId("chain-step").all();
  const steps: SequenceStep[] = [];
  for (const row of rows) {
    const number = /^(\d+)Step \d+:/.exec((await row.textContent()) ?? "")?.[1];
    const title = await row.getByTestId("chain-step-title").textContent();
    steps.push({ number: Number(number), title: (title ?? "").trim() });
  }
  return steps;
}

test("map: step markers are numbered and named exactly like the Sequence tab and stay off the pulse ring", async ({
  page,
}) => {
  await login(page, USER.commander);
  const sequence = await sequenceOnDecision(page, PS17);
  expect(sequence.length).toBeGreaterThan(2);
  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  await page.waitForTimeout(900);
  const markers = await page
    .getByTestId("chain-stop")
    .evaluateAll((els) =>
      els.map((e) => [Number(e.getAttribute("data-step")), e.getAttribute("aria-label")]),
    );
  const numbers = markers.map(([n]) => n as number);
  expect(numbers).toEqual([...numbers].sort((a, b) => a - b));
  for (const [n, label] of markers) {
    const step = sequence.find((s) => s.number === n);
    expect(step, `step ${n} is in the Sequence tab`).toBeDefined();
    expect(label).toContain(`Step ${n}: ${step?.title}`);
  }
  const named = markers.map(([, label]) => label as string);
  expect(new Set(named).size).toBe(named.length);

  const centre = (r: DOMRect) => ({ x: r.x + r.width / 2, y: r.y + r.height / 2 });
  const { pulses, badges } = await page.evaluate(() => {
    const read = (sel: string) =>
      [...document.querySelectorAll(sel)].map((e) => {
        const r = e.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height, step: e.getAttribute("data-asset") };
      });
    return { pulses: read('[data-testid="selected-pulse"]'), badges: read('[data-testid="chain-stop"]') };
  });
  expect(pulses.length).toBeGreaterThan(0);
  for (const pulse of pulses)
    for (const badge of badges) {
      const a = centre(pulse as unknown as DOMRect);
      const b = centre(badge as unknown as DOMRect);
      const gap = Math.hypot(a.x - b.x, a.y - b.y);
      const sameMarker = gap < 2;
      if (!sameMarker) expect(gap, "a badge sits on another marker's pulse ring").toBeGreaterThan(40);
    }
});

test("map: the camera keeps the user's zoom across history steps and re-frames on Clear selection", async ({
  page,
}) => {
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  await page.waitForTimeout(700);
  const camera = () =>
    page.evaluate(() => {
      const m = (window as unknown as { __sgwMap: TestMap }).__sgwMap;
      return { zoom: m.getZoom(), lng: m.getCenter().lng, lat: m.getCenter().lat };
    });
  await page.evaluate(() =>
    (window as unknown as { __sgwMap: TestMap }).__sgwMap.jumpTo({ zoom: 7.4, center: [-81.6, 33.4] }),
  );
  const before = await camera();
  const slider = page.getByRole("slider", { name: "Advisory history" });
  await slider.focus();
  for (const key of ["ArrowLeft", "ArrowLeft", "Home", "End"]) {
    await page.keyboard.press(key);
    await page.waitForTimeout(700);
    const after = await camera();
    expect(Math.abs(after.zoom - before.zoom)).toBeLessThan(0.01);
    expect(Math.abs(after.lng - before.lng)).toBeLessThan(0.01);
    expect(Math.abs(after.lat - before.lat)).toBeLessThan(0.01);
  }

  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  await page.waitForTimeout(900);
  await page.evaluate(() =>
    (window as unknown as { __sgwMap: TestMap }).__sgwMap.jumpTo({ zoom: 6.8, center: [-81.7, 33.5] }),
  );
  await page.keyboard.press("Tab");
  await page.getByRole("button", { name: "Clear selection" }).click();
  await page.waitForTimeout(900);
  expect((await camera()).zoom).toBeLessThan(6.8);
});

test("map: layers and legend start collapsed, one at a time on a narrow map, and remember what the user opened", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1288, height: 742 });
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  await expect(page.getByTestId("layer-panel")).toHaveCount(0);
  await expect(page.getByTestId("legend-toggle")).toBeVisible();
  const share = (selector: string) =>
    page.evaluate((sel) => {
      const map = document.querySelector('[data-testid="map"]')?.getBoundingClientRect();
      const area = [...document.querySelectorAll(sel)].reduce((sum, e) => {
        const r = e.getBoundingClientRect();
        return sum + r.width * r.height;
      }, 0);
      return map ? area / (map.width * map.height) : 1;
    }, selector);
  expect(await share('[data-testid="layer-toggle"], [data-testid="legend-toggle"]')).toBeLessThan(0.05);

  await page.getByTestId("layer-toggle").click();
  expect(await share('[data-testid="layer-panel"]')).toBeLessThan(0.22);
  await page.getByTestId("legend-toggle").click();
  await expect(page.getByTestId("layer-panel")).toHaveCount(0);
  expect(await share('[data-testid="map-legend"]')).toBeLessThan(0.22);

  await page.reload();
  await mapReady(page);
  await expect(page.getByTestId("layer-panel")).toHaveCount(0);
  await expect(page.getByTestId("map-legend")).toContainText("Outage risk");
  await page.getByTestId("layer-toggle").click();
  await page.reload();
  await mapReady(page);
  await expect(page.getByTestId("layer-panel")).toBeVisible();
  await page.getByRole("button", { name: "Collapse layers" }).click();
  await page.reload();
  await mapReady(page);
  await expect(page.getByTestId("layer-panel")).toHaveCount(0);
});

test("map: the values switch says why nothing shows while zoomed out, and the airport gust option follows airport wind", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1288, height: 742 });
  await login(page, USER.commander);
  await page.goto("/map");
  await mapReady(page);
  await page.getByTestId("layer-toggle").click();
  const panel = page.getByTestId("layer-panel");
  await page.evaluate(() => (window as unknown as { __sgwMap: TestMap }).__sgwMap.jumpTo({ zoom: 5 }));
  await expect(panel.getByText("Zoom in to see them")).toBeVisible();
  await expect(page.getByTestId("map-value")).toHaveCount(0);
  await page.evaluate(() => (window as unknown as { __sgwMap: TestMap }).__sgwMap.jumpTo({ zoom: 7.5 }));
  await expect(panel.getByText("Zoom in to see them")).toHaveCount(0);
  await expect(page.getByTestId("map-value").first()).toBeVisible();

  await expect(panel.getByRole("switch", { name: "Airport gust values" })).toHaveCount(0);
  await panel.getByRole("switch", { name: "Airport wind" }).click();
  await expect(panel.getByRole("switch", { name: "Airport gust values" })).toBeChecked();
});

test("map: points, step markers, wind arrows and values stay pinned to their coordinates while the map moves", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1288, height: 742 });
  await login(page, USER.commander);
  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  await page.getByTestId("layer-toggle").click();
  await page.getByTestId("layer-panel").getByRole("switch", { name: "Airport wind" }).click();
  await expect(page.getByTestId("wind-station").first()).toBeAttached();
  await page.waitForTimeout(900);
  await page.getByRole("button", { name: "Collapse layers" }).click();

  const run = await page.evaluate(async () => {
    type Pin = { lngLat: [number, number]; dx: number; dy: number };
    const map = (
      window as unknown as {
        __sgwMap: TestMap & {
          on(e: string, f: () => void): void;
          off(e: string, f: () => void): void;
          once(e: string, f: () => void): void;
          easeTo(o: object): void;
          flyTo(o: object): void;
        };
      }
    ).__sgwMap;
    let worst = 0;
    let samples = 0;
    const kinds = new Set<string>();
    const sample = () => {
      const host = map.getContainer().getBoundingClientRect();
      for (const el of document.querySelectorAll<HTMLElement>("[data-pin]")) {
        const [lon, lat, dx, dy] = (el.dataset.pin ?? "").split(",").map(Number);
        const pin: Pin = { lngLat: [lon as number, lat as number], dx: dx as number, dy: dy as number };
        const r = el.getBoundingClientRect();
        if (r.width === 0) continue;
        const shifting = [el, el.parentElement].some((node) =>
          node?.getAnimations().some((a) => a instanceof CSSTransition),
        );
        if (shifting) continue;
        const p = map.project(pin.lngLat);
        const gap = Math.hypot(
          r.left + r.width / 2 - (host.left + p.x + pin.dx),
          r.top + r.height / 2 - (host.top + p.y + pin.dy),
        );
        worst = Math.max(worst, gap);
        samples += 1;
        kinds.add(el.dataset.testid ?? "");
      }
    };
    const move = (fn: () => void) =>
      new Promise<void>((done) => {
        map.once("moveend", () => done());
        fn();
      });
    map.on("render", sample);
    const c = map.getCenter();
    await move(() => map.easeTo({ center: [c.lng + 0.08, c.lat - 0.05], duration: 700 }));
    await move(() => map.easeTo({ zoom: map.getZoom() - 1.4, duration: 700 }));
    await move(() => map.easeTo({ zoom: map.getZoom() + 2, duration: 700 }));
    await move(() => map.flyTo({ center: [c.lng - 0.2, c.lat + 0.1], zoom: 9, duration: 1100 }));
    map.off("render", sample);
    return { worst, samples, kinds: [...kinds] };
  });
  await page.waitForTimeout(400);
  const settled = await page.evaluate(() => {
    const map = (window as unknown as { __sgwMap: TestMap }).__sgwMap;
    const host = map.getContainer().getBoundingClientRect();
    let worst = 0;
    let culprit = "";
    for (const el of document.querySelectorAll<HTMLElement>("[data-pin]")) {
      const [lon, lat, dx, dy] = (el.dataset.pin ?? "").split(",").map(Number);
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      const p = map.project([lon as number, lat as number]);
      const gap = Math.hypot(
        r.left + r.width / 2 - (host.left + p.x + (dx as number)),
        r.top + r.height / 2 - (host.top + p.y + (dy as number)),
      );
      if (gap > worst) culprit = `${el.dataset.testid} ${el.dataset.pin}`;
      worst = Math.max(worst, gap);
    }
    return `${worst} ${culprit}`;
  });
  expect(Number.parseFloat(settled), settled).toBeLessThan(1);
  expect(run.samples).toBeGreaterThan(100);
  expect(run.kinds).toEqual(
    expect.arrayContaining(["chain-stop", "map-value", "wind-station", "station-value", "selected-pulse"]),
  );
  expect(run.worst).toBeLessThan(2);
});

test("map: step badges keep their order and offsets for a zoom range and change only across its boundary", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1288, height: 742 });
  await login(page, USER.commander);
  await page.goto(`/map?d=${PS17}`);
  await mapReady(page);
  await page.waitForTimeout(900);
  type Ctl = {
    jumpTo(o: object): void;
    easeTo(o: object): void;
    panBy(o: [number, number], c: object): void;
    once(e: string, f: () => void): void;
    on(e: string, f: () => void): void;
    off(e: string, f: () => void): void;
    getZoom(): number;
  };
  const layout = async () => {
    await page.waitForTimeout(350);
    return page
      .getByTestId("chain-stop")
      .evaluateAll((els) =>
        els.map(
          (e) =>
            `${e.getAttribute("data-step")}|${e.getAttribute("data-asset")}|${e.getAttribute("data-pin")?.split(",").slice(2)}`,
        ),
      );
  };
  const jump = (zoom: number) =>
    page.evaluate((z) => (window as unknown as { __sgwMap: Ctl }).__sgwMap.jumpTo({ zoom: z }), zoom);

  await jump(9.05);
  const first = await layout();
  expect(first.length).toBeGreaterThan(3);
  const numbers = first.map((l) => Number(l.split("|")[0]));
  expect(numbers).toEqual([...numbers].sort((a, b) => a - b));

  await jump(9.3);
  expect(await layout(), "same zoom range: same order and offsets").toEqual(first);
  await jump(9.45);
  expect(await layout()).toEqual(first);

  await page.evaluate(() =>
    (window as unknown as { __sgwMap: Ctl }).__sgwMap.panBy([140, -90], { duration: 0 }),
  );
  expect(await layout(), "panning does not rearrange the badges").toEqual(first);

  await jump(8.2);
  const lower = await layout();
  await jump(9.2);
  expect(await layout(), "coming back to a range gives the same layout, whatever the way there").toEqual(
    first,
  );
  await jump(8.4);
  expect(await layout()).toEqual(lower);

  const seen = await page.evaluate(
    () =>
      new Promise<string[]>((done) => {
        const map = (window as unknown as { __sgwMap: Ctl }).__sgwMap;
        map.jumpTo({ zoom: 9.02 });
        const read = () =>
          [...document.querySelectorAll('[data-testid="chain-stop"]')]
            .map((e) => e.getAttribute("data-pin"))
            .join(";");
        const frames = new Set<string>();
        const sample = () => frames.add(read());
        requestAnimationFrame(() => {
          map.on("render", sample);
          map.once("moveend", () => {
            map.off("render", sample);
            done([...frames]);
          });
          map.easeTo({ zoom: 9.48, duration: 600 });
        });
      }),
  );
  expect(seen, "while zooming inside one range the badges never move or swap").toHaveLength(1);
});

test("forecast: stepping back in history does not move the content below the bar", async ({ page }) => {
  await login(page, USER.commander);
  await page.goto("/forecast");
  const bar = page.getByTestId("history-bar");
  await expect(bar).toBeVisible();
  const below = () =>
    page
      .getByRole("tablist")
      .first()
      .evaluate((el) => el.getBoundingClientRect().top);
  const top = await below();
  await bar.getByRole("slider", { name: "Advisory history" }).focus();
  await page.keyboard.press("Home");
  await expect(bar.getByRole("button", { name: "Back to live" })).toBeVisible();
  expect(await below()).toBe(top);
  await page.keyboard.press("End");
  expect(await below()).toBe(top);
});
