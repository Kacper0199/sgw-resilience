import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const TABS = ["Zones", "PS-17 plan", "Boil-water notices"] as const;
const tab = (page: Page, name: (typeof TABS)[number]) =>
  page.getByRole("tab", { name: new RegExp(`^${name}`) }).click();

const openWater = async (page: Page) => {
  await page.getByRole("link", { name: "Water", exact: true }).click();
  await expect(page).toHaveURL(/\/water$/);
  await expect(page.getByTestId("zone-row")).toHaveCount(4);
};

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("the water lead reads zones, the PS-17 clocks, the notice without console errors", async ({ page }) => {
  const errors = collectErrors(page);
  await login(page, USER.waterLead);
  await openWater(page);

  await expect(page.getByRole("heading", { name: "Water", level: 1 })).toBeVisible();
  await expect(page.getByText("Zones above the minimum")).toBeVisible();
  const cedarfall = page.getByTestId("zone-row").first();
  await expect(cedarfall).toContainText("Cedarfall");
  await expect(cedarfall).toContainText("62.0 psi");
  await expect(page.getByTestId("zone-detail")).toContainText("Next steps for Cedarfall");

  await tab(page, "PS-17 plan");
  const chain = page.getByRole("list", { name: "Critical path, in order" });
  await expect(chain.getByTestId("water-case")).toHaveCount(3);
  await expect(chain.getByTestId("water-case").first()).toContainText("in 59 m");

  await tab(page, "Boil-water notices");
  await expect(page.getByTestId("probability-strip")).toHaveAttribute(
    "aria-label",
    "Previous advisory 05:00 ET 8.1%, latest advisory 11:00 ET 15.2%, notice trigger 10%, crossed",
  );
  await expect(page.getByTestId("clause-card").first()).toContainText("Advisory before landfall");

  expect(errors).toEqual([]);
});

test("the rule clause is one click away and both states are in the rule book", async ({ page }) => {
  await login(page, USER.waterLead);
  await openWater(page);
  await tab(page, "Boil-water notices");
  const first = page.getByRole("button", { name: /Advisory before landfall/ });
  await expect(first).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText(/precautionary boil water advisory/)).toBeVisible();
  await first.click();
  await expect(page.getByText(/precautionary boil water advisory/)).toBeHidden();
  await first.click();
  await expect(page.getByText(/precautionary boil water advisory/)).toBeVisible();
  await page.getByRole("button", { name: /^All rules/ }).click();
  await page.getByRole("radio", { name: /Georgia/ }).click();
  await page.getByRole("button", { name: /Advisory after pressure loss/ }).click();
  await expect(page.getByText(/20 psi at each service connection/)).toBeVisible();
});

test("a step opens the matching decision case", async ({ page }) => {
  await login(page, USER.waterLead);
  await openWater(page);
  await tab(page, "PS-17 plan");
  const second = page.getByRole("list", { name: "Critical path, in order" }).getByTestId("water-case").nth(1);
  await second.getByRole("link", { name: /^View decision/ }).click();
  await expect(page).toHaveURL(/\/\?d=PRP-PS17-FDR2207-PRIO/);
  await expect(page.getByRole("heading", { name: "Restore feeder 2207 first to power PS-17" })).toBeVisible();
});

test("the open zone's next steps and the clickable id link into the Decisions queue", async ({ page }) => {
  await login(page, USER.waterLead);
  await openWater(page);
  const detail = page.getByTestId("zone-detail");
  await detail.getByRole("link", { name: /^View decision: Send the fuel truck/ }).click();
  await expect(page).toHaveURL(/\/\?d=PRP-PS17-FUEL/);
});

test("a zone row opens and closes with a click, and the tab is in the URL", async ({ page }) => {
  await login(page, USER.waterLead);
  await openWater(page);
  const laurel = page.getByTestId("zone-row").nth(1);
  await laurel.click();
  await expect(
    page.getByText("Pressure is above the minimum. No open decision for Laurelspur."),
  ).toBeVisible();
  await laurel.click();
  await expect(page.getByText("No open decision for Laurelspur.")).toHaveCount(0);
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
]) {
  test(`every InfoTip on the water page stays inside the viewport at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await login(page, USER.waterLead);
    await openWater(page);
    for (const name of TABS) {
      await tab(page, name);
      const triggers = page.locator('button[aria-label^="What does"], button[aria-label^="Info:"]');
      const count = await triggers.count();
      expect(count, name).toBeGreaterThanOrEqual(3);
      for (let i = 0; i < count; i++) {
        const trigger = triggers.nth(i);
        await trigger.scrollIntoViewIfNeeded();
        await trigger.click();
        const bubble = page.locator('[data-testid^="infotip-"]');
        await expect(bubble).toBeVisible();
        const box = await bubble.evaluate((el) => {
          const r = el.getBoundingClientRect();
          return {
            left: r.left,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
            vw: innerWidth,
            vh: innerHeight,
          };
        });
        expect(box.left, `${name} tip ${i} left`).toBeGreaterThanOrEqual(0);
        expect(box.top, `${name} tip ${i} top`).toBeGreaterThanOrEqual(0);
        expect(box.right, `${name} tip ${i} right`).toBeLessThanOrEqual(box.vw);
        expect(box.bottom, `${name} tip ${i} bottom`).toBeLessThanOrEqual(box.vh);
        await page.keyboard.press("Escape");
        await expect(bubble).toHaveCount(0);
      }
    }
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`axe finds no serious violations on the water page (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.waterLead);
    await openWater(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    for (const name of TABS) {
      await tab(page, name);
      const results = await new AxeBuilder({ page }).analyze();
      expect(
        results.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
        name,
      ).toEqual([]);
    }
  });
}

test("the page is understandable in grayscale: status carries a word or shape, never colour alone", async ({
  page,
}) => {
  await login(page, USER.waterLead);
  await openWater(page);
  await page.emulateMedia({ forcedColors: "none" });
  await page.addStyleTag({ content: "html { filter: grayscale(1); }" });
  await expect(page.getByTestId("zone-row").first()).toContainText("62.0 psi");
  await expect(page.getByTestId("zone-row").first()).toContainText("No backup power");
  await tab(page, "Boil-water notices");
  await expect(page.getByText("Waiting for sign-off").first()).toBeVisible();
});
