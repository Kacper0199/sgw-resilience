import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SIZES = [
  { width: 1288, height: 742 },
  { width: 1512, height: 900 },
] as const;

async function withZoneRules(page: Page, theme: "light" | "dark" = "light") {
  await page.addInitScript((t) => {
    sessionStorage.setItem("sgw.mock.zone_rules", "1");
    localStorage.setItem("sgw.theme", t);
  }, theme);
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function overflowing(page: Page, readingPage: boolean) {
  return page.evaluate((reading) => {
    const out: string[] = [];
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      if (style.display === "none" || rect.width === 0 || rect.height === 0) continue;
      if (["auto", "scroll"].includes(style.overflowX) && el.scrollWidth - el.clientWidth > 1) {
        out.push(`x ${el.tagName.toLowerCase()}.${String(el.className).split(" ").slice(0, 3).join(".")}`);
      }
      if (reading && el.id === "main") continue;
      if (el.closest("[data-scroll-region]")) continue;
      if (["auto", "scroll"].includes(style.overflowY) && el.scrollHeight - el.clientHeight > 1) {
        out.push(`y ${el.tagName.toLowerCase()}.${String(el.className).split(" ").slice(0, 3).join(".")}`);
      }
    }
    return out;
  }, readingPage);
}

test("each zone shows its notice as five steps, the zone that needs a signature first", async ({ page }) => {
  const errors = collectErrors(page);
  await withZoneRules(page);
  await login(page, USER.waterLead);
  await page.goto("/water?tab=advisories");
  const rows = page.getByTestId("bwa-row");
  await expect(rows).toHaveCount(4);
  await expect(rows.getByRole("heading", { level: 3 })).toHaveText([
    "Laurelspur",
    "Copperleaf",
    "Deerwater",
    "Cedarfall",
  ]);
  const steppers = page.getByTestId("notice-stepper");
  await expect(steppers).toHaveCount(4);
  const current = await steppers.evaluateAll((els) => els.map((e) => e.getAttribute("data-current")));
  expect(current).toEqual(["due", "lift", "samples", "lifted"]);
  await expect(rows.nth(0).getByRole("list", { name: "Notice steps for Laurelspur" })).toBeVisible();
  await expect(rows.nth(0)).toContainText("Waiting for sign-off");
  await expect(rows.nth(1)).toContainText("Lift waiting for sign-off");
  await expect(rows.nth(2)).toContainText("Waiting for clean samples");
  await expect(rows.nth(3)).toContainText("Lifted");
  await rows
    .nth(1)
    .getByRole("link", { name: /^View decision/ })
    .click();
  await expect(page).toHaveURL(/\/\?d=PRP-ZR-COPPERLEAF-LIFT/);
  expect(errors).toEqual([]);
});

test("the zones table carries every zone's notice step and opens the first zone with an open decision", async ({
  page,
}) => {
  await withZoneRules(page);
  await login(page, USER.waterLead);
  await page.goto("/water");
  const zones = page.getByTestId("zone-row");
  await expect(zones).toHaveCount(4);
  await expect(zones.nth(1)).toContainText("Waiting for sign-off");
  await expect(zones.nth(2)).toContainText("Lift waiting for sign-off");
  await expect(zones.nth(3)).toContainText("Waiting for clean samples");
  await expect(zones.nth(0)).toContainText("Lifted");
  await expect(page.getByTestId("zone-detail")).toHaveCount(1);
  await expect(page.getByTestId("zone-detail")).toContainText("Send a water tanker to Tallowbranch hospital");
  await expect(page.getByTestId("zone-detail")).toContainText("feeder 2219");
  await expect(page.getByTestId("zone-detail")).not.toContainText("FDR-AIK");
});

test("decisions read in plain words with an icon and a name for what each one does", async ({ page }) => {
  const errors = collectErrors(page);
  await withZoneRules(page);
  await login(page, USER.commander);
  const rows = page.locator("tr", { hasText: "Set the restoration order of feeder 2219 and feeder 2207" });
  await expect(rows.first()).toBeVisible();
  await expect(page.locator("tbody")).not.toContainText("FDR-AIK-2219");
  await expect(rows.first()).toContainText("Restoration order");
  await page.locator("tr", { hasText: "Send a water tanker to Tallowbranch hospital" }).first().click();
  await expect(page.getByTestId("action-mark").first()).toHaveText("Water tanker");
  await expect(
    page.getByRole("heading", { name: "Send a water tanker to Tallowbranch hospital" }),
  ).toBeVisible();
  await page
    .locator("tr", { hasText: "Lift the boil water advisory for the Copperleaf zone" })
    .first()
    .click();
  await expect(page.getByTestId("action-mark").first()).toHaveText("Lift a notice");
  expect(errors).toEqual([]);
});

for (const size of SIZES) {
  for (const theme of ["light", "dark"] as const) {
    test(`Water and Decisions fit without a scrollbar at ${size.width}x${size.height} (${theme})`, async ({
      page,
    }) => {
      test.setTimeout(120_000);
      await page.setViewportSize(size);
      await withZoneRules(page, theme);
      await login(page, USER.waterLead);
      const failures: string[] = [];
      for (const [route, reading] of [
        ["/water", true],
        ["/water?tab=plan", true],
        ["/water?tab=advisories", true],
        ["/", false],
      ] as const) {
        await page.goto(route);
        await page.locator("main h1, main h2").first().waitFor();
        await page.waitForTimeout(700);
        failures.push(...(await overflowing(page, reading)).map((o) => `${route} ${o}`));
      }
      expect(failures).toEqual([]);
    });
  }
}
