import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, switchUser, USER } from "./support/login";

const TABS = ["Crews", "Plan", "Damage photos"] as const;
const tab = (page: Page, name: (typeof TABS)[number]) =>
  page.getByRole("tab", { name: new RegExp(`^${name}`) }).click();

const openCrews = async (page: Page) => {
  await page.getByRole("link", { name: "Crews", exact: true }).click();
  await expect(page).toHaveURL(/\/crews$/);
  await expect(page.getByTestId("crew-row")).toHaveCount(6);
};

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("logistics reads the plan options and the yards in one tab, with no option preselected", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.logistics);
  await openCrews(page);
  await expect(page.getByText("Crews reporting")).toBeVisible();

  await tab(page, "Plan");
  const heads = page.getByTestId("plan-table").getByRole("columnheader");
  await expect(heads.nth(1)).toContainText("Standard plan");
  await expect(heads.nth(2)).toContainText("A: Same cost, better placed");
  await expect(heads.nth(4)).toContainText("C: Own crews first");
  await expect(page.getByTestId("plan-row-expected")).toContainText("14.1 M");
  await expect(page.getByTestId("plan-row-expected")).toContainText("9.9 M");
  await expect(page.getByText("Selected", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "About these numbers" }).click();
  await expect(page.getByTestId("plan-facts")).toContainText("63,435 customer-hours");
  await expect(page.getByTestId("plan-facts")).toContainText("186,844");
  await expect(page.getByTestId("plan-limits")).toContainText("±20% per yard");
  await page.keyboard.press("Escape");

  await expect(page.getByTestId("yard-row")).toHaveCount(11);
  await expect(page.getByTestId("generator-row")).toHaveCount(4);
  expect(errors).toEqual([]);
});

test("before landfall the damage photos tab says photos come later; a photo link still opens the photo", async ({
  page,
}) => {
  await login(page, USER.logistics);
  await page.goto("/crews?photo=ladi-v2-test-0034");
  await expect(page.getByRole("tab", { name: /Damage photos/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("photo-preview")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("No damage photos yet.")).toBeVisible();
});

test("a yard link opens the Plan tab on that yard", async ({ page }) => {
  await login(page, USER.executive);
  await page.goto("/crews?yard=STG-RCH-MILLPOND-YARD");
  await expect(page.getByRole("tab", { name: /^Plan/ })).toHaveAttribute("aria-selected", "true");
  const marked = page.locator('[data-testid="yard-row"][aria-current="true"]');
  await expect(marked).toHaveCount(1);
  await expect(marked).toContainText("Millpond yard");
});

test("dispatch: operations assigns a crew, logistics signs, the crew moves, the decision lists it", async ({
  page,
}) => {
  const errors = collectErrors(page);
  const menu = async (crew: string, item: string) => {
    await page.getByRole("button", { name: `Actions for ${crew}` }).click();
    await page.getByRole("menuitem", { name: item }).click();
  };
  const row = (crew: string) => page.getByTestId("crew-row").filter({ hasText: crew });

  await login(page, USER.dutyManager);
  await openCrews(page);
  await menu("Harrier 3", "Assign…");
  const dialog = page.getByTestId("dispatch-dialog");
  await dialog.getByLabel("Assign to").selectOption({ label: "Hook up the portable generator at PS-17" });
  await dialog.getByRole("button", { name: "Assign" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(/assigned to Hook up the portable generator/)).toBeVisible();
  await expect(row("Harrier 3")).toContainText("Waiting for Logistics");

  await switchUser(page, USER.logistics);
  await openCrews(page);
  await menu("Harrier 3", "Sign assignment");
  await expect(row("Harrier 3")).toContainText("Assigned");
  await menu("Harrier 3", "Mark on the way");
  await expect(row("Harrier 3")).toContainText("On the way");

  await row("Harrier 3")
    .getByRole("link", { name: /Hook up the portable generator/ })
    .click();
  await expect(page.getByTestId("assigned-crews")).toContainText("Harrier 3");
  await expect(page.getByTestId("assigned-crews")).toContainText("On the way");
  expect(errors).toEqual([]);
});

test("dispatch: a crew is marked blocked with a reason; read-only personas and the admin get no menu", async ({
  page,
}) => {
  await login(page, USER.dutyManager);
  await openCrews(page);
  await page.getByRole("button", { name: "Actions for Merlin 2" }).click();
  await page.getByRole("menuitem", { name: "Mark blocked…" }).click();
  const dialog = page.getByTestId("dispatch-dialog");
  await dialog.getByLabel("Reason").selectOption({ label: "Road closed" });
  await dialog.getByRole("button", { name: "Mark blocked" }).click();
  const merlin = page.getByTestId("crew-row").filter({ hasText: "Merlin 2" });
  await expect(merlin).toContainText("Blocked");
  await expect(merlin).toContainText("Road closed");

  await switchUser(page, USER.admin);
  await openCrews(page);
  await expect(page.getByTestId("crew-row").first()).toBeVisible();
  await expect(page.getByTestId("crew-menu")).toHaveCount(0);

  await switchUser(page, USER.executive);
  await page.goto("/crews?crew=CRW-OSPREY-07");
  await expect(page.getByTestId("crew-row")).toHaveCount(6);
  await expect(page.getByTestId("crew-menu")).toHaveCount(0);
  await expect(page.getByTestId("crew-row").filter({ hasText: "Osprey 7" })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("damage photos open in a preview with the model's scores; Esc closes it", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("sgw.mock.after_landfall", "1"));
  await login(page, USER.logistics);
  await openCrews(page);
  await tab(page, "Damage photos");
  await page
    .getByRole("button", { name: /^Open photo/ })
    .first()
    .click();
  const preview = page.getByTestId("photo-preview");
  await expect(preview.getByTestId("photo-full")).toBeVisible();
  expect(
    await preview.getByTestId("photo-full").evaluate((el) => (el as HTMLImageElement).naturalWidth),
  ).toBeGreaterThan(0);
  await expect(preview.getByRole("list", { name: "What the model sees" })).toContainText("%");
  await expect(preview.getByRole("link")).toHaveCount(0);
  await expect(preview.getByText(/^1 of \d+/)).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(preview.getByText(/^2 of \d+/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(preview).toHaveCount(0);
});

test("the crews table sorts and the damage photos show the clear miss", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("sgw.mock.after_landfall", "1"));
  await login(page, USER.logistics);
  await openCrews(page);
  const crewsTable = page.getByRole("table", { name: "Crews (sortable)" });
  await page.getByRole("button", { name: /People/ }).click();
  await expect(crewsTable.getByRole("columnheader", { name: /People/ })).toHaveAttribute(
    "aria-sort",
    "ascending",
  );
  await expect(page.getByTestId("crew-row").last()).toContainText("Talon 11");
  await page.getByRole("button", { name: /People/ }).click();
  await expect(page.getByTestId("crew-row").first()).toContainText("Talon 11");

  await tab(page, "Damage photos");
  await expect(page.getByTestId("damage-case")).toHaveCount(6);
  const cases = page.getByTestId("damage-case");
  await expect(cases.nth(3)).toHaveAttribute("data-miss", "true");
  await page.getByRole("button", { name: "About the damage model" }).click();
  await expect(page.getByTestId("visible-miss")).toContainText("ranks only 4th of 4 damaged cases");
  await expect(page.getByTestId("two-tier")).toContainText("lowest 0.20");
  await page.keyboard.press("Escape");
  const thumbs = cases.first().locator("img");
  await expect(thumbs).toHaveCount(5);
  for (const img of await thumbs.all()) {
    await expect(img).toHaveJSProperty("complete", true);
    expect(await img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  }
  await page.getByRole("radio", { name: "Photos" }).click();
  await expect(page.getByTestId("damage-photo")).toHaveCount(12);
  await page.getByRole("radio", { name: "Cases" }).click();
  await page
    .getByTestId("damage-case")
    .first()
    .getByRole("button", { name: /damage$/ })
    .click();
  await expect(page.getByTestId("photo-preview")).toBeVisible();
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
]) {
  test(`every InfoTip on the crews page stays inside the viewport at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await login(page, USER.logistics);
    await openCrews(page);
    for (const name of TABS) {
      await tab(page, name);
      const triggers = page.locator('button[aria-label^="What does"], button[aria-label^="Info:"]');
      const count = await triggers.count();
      expect(count, name).toBeGreaterThanOrEqual(1);
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
  test(`axe finds no serious violations on the crews page (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.logistics);
    await openCrews(page);
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
