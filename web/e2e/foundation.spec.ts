import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SHOTS = process.env.SGW_SHOTS ?? "test-results/shots";

const serious = (violations: { impact?: string | null }[]) =>
  violations.filter((v) => v.impact === "serious" || v.impact === "critical");

for (const theme of ["light", "dark"] as const) {
  test(`axe finds no serious violations on /design-check (${theme}) and the shell`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await page.goto("/design-check");
    const panel = page.getByTestId(`specimen-${theme}`);
    await expect(panel.getByRole("heading", { name: /Decisions/ })).toBeVisible();
    const check = await new AxeBuilder({ page }).include(`[data-testid=specimen-${theme}]`).analyze();
    expect(serious(check.violations)).toEqual([]);
    await page.screenshot({ path: `${SHOTS}/design-check-1440-${theme}.png`, fullPage: true });

    await login(page, USER.commander);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const shell = await new AxeBuilder({ page }).analyze();
    expect(serious(shell.violations)).toEqual([]);
    await page.screenshot({ path: `${SHOTS}/shell-1440-${theme}.png` });
  });
}

test("the shell at 390 px has a bottom tab bar and no sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, USER.commander);
  await expect(page.getByTestId("tab-bar")).toBeVisible();
  await expect(page.getByTestId("sidebar")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByTestId("tab-bar").getByRole("button", { name: "More" }).click();
  await expect(page.getByRole("menuitem", { name: "System health" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.screenshot({ path: `${SHOTS}/shell-390-light.png` });
});

test("Reduce transparency is in the person menu and survives a reload", async ({ page }) => {
  await login(page, USER.commander);
  await page.getByRole("button", { name: /Signed in as/ }).click();
  await page.getByRole("menuitemcheckbox", { name: "Reduce transparency" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-transparency", "reduced");
  await page.keyboard.press("Escape");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-transparency", "reduced");
});

test("sidebar groups collapse and the sidebar folds to a rail", async ({ page }) => {
  await login(page, USER.commander);
  const inform = page.getByRole("button", { name: /^Inform/ });
  await expect(page.getByRole("link", { name: "System health", exact: true })).toBeVisible();
  await inform.click();
  await expect(page.getByRole("link", { name: "System health", exact: true })).toBeHidden();
  await inform.click();
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(page.getByRole("link", { name: "Decisions", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Decisions", exact: true }).hover();
  await expect(page.getByRole("tooltip")).toContainText("Decisions");
});

test("design-check: table rows move with arrow keys; dialog traps focus, closes on Esc and returns focus", async ({
  page,
}) => {
  await page.goto("/design-check");
  const light = page.getByTestId("specimen-light");
  const rows = light.locator("table").first().locator("tr[data-row]");
  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(rows.nth(1)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");

  const opener = light.getByRole("button", { name: "Open dialog" });
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Sign as Command" });
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 8; i++) await page.keyboard.press("Tab");
  expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
  await page.screenshot({ path: `${SHOTS}/design-check-dialog-1440-light.png` });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();

  await light.getByRole("button", { name: "Open sheet" }).click();
  await expect(page.getByRole("dialog", { name: "Cedarfall zone" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
