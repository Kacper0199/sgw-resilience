import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { DEMO_PASSWORD, login, USER } from "./support/login";

const seriousViolations = async (page: import("@playwright/test").Page) =>
  (await new AxeBuilder({ page }).analyze()).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );

for (const theme of ["light", "dark"] as const) {
  test(`axe finds no serious violations on the sign-in page, chooser open, ${theme}`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(await seriousViolations(page)).toEqual([]);
    await page.getByRole("button", { name: /^Demo people/ }).click();
    await page.getByRole("button", { name: /^Other accounts/ }).click();
    await expect(page.getByRole("listbox", { name: "Other accounts" })).toBeVisible();
    expect(await seriousViolations(page)).toEqual([]);
  });
}

test("the chooser is reachable by keyboard: arrows move, Enter fills the ID and the demo password, Escape returns focus", async ({
  page,
}) => {
  await page.goto("/login");
  const trigger = page.getByRole("button", { name: /^Demo people/ });
  await page.getByLabel("User ID").focus();
  await page.keyboard.press("ArrowDown");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator('[role="option"]').first()).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await trigger.press("Enter");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("User ID")).toHaveValue(USER.waterLead);
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue(DEMO_PASSWORD);
  await expect(page.getByText("Signs as Water operations")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("top-band")).toBeVisible();
});

test("an account under Other accounts signs in through the chooser", async ({ page }) => {
  await login(page, USER.auditor, { via: "chooser" });
  await expect(page.getByTestId("top-band")).toBeVisible();
});

test("at 390 px the chooser is a bottom sheet that closes on its scrim", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await page.getByRole("button", { name: /^Demo people/ }).click();
  const list = page.getByRole("listbox", { name: "Demo people" });
  await expect(list.getByRole("option")).toHaveCount(7);
  const sheet = list.locator("xpath=..");
  await expect
    .poll(async () => {
      const box = await sheet.boundingBox();
      return box ? [box.x, box.width, Math.round(box.y + box.height)] : null;
    })
    .toEqual([0, 390, 844]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.mouse.click(195, 40);
  await expect(list).toBeHidden();
});

test("a wrong password shows one sentence and keeps the form", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("User ID").fill("nobody_01");
  await page.getByLabel("Password", { exact: true }).fill("nope");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(/^[A-Z][^.]+\.$/);
  await expect(page.getByLabel("User ID")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByLabel("User ID")).toHaveValue("nobody_01");
});

test("with reduced motion the glow stands still, and with reduced transparency it becomes a flat tint", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/login");
  const blob = page.locator(".lg-navy");
  await expect(blob).toHaveCSS("animation-name", "none");
  await page.evaluate(() => {
    document.documentElement.dataset.transparency = "reduced";
  });
  await expect(blob).toBeHidden();
});
