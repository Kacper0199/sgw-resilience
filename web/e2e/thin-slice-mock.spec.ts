import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, switchUser, USER } from "./support/login";

const PS17 = "PRP-PS17-FDR2207-PRIO";

async function sign(page: Page) {
  await page.getByRole("button", { name: /^Sign as / }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Sign", exact: true }).click();
  const password = dialog.getByLabel("Enter your password to sign");
  if (await password.isVisible({ timeout: 1500 }).catch(() => false)) {
    await password.fill("demo");
    await dialog.getByRole("button", { name: "Sign", exact: true }).click();
  }
}

async function consoleErrors(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("login, queue, stream and the two-function T3 signature", async ({ page }) => {
  const errors = await consoleErrors(page);
  await login(page, USER.commander);

  await expect(page.getByRole("heading", { name: "Decisions" })).toBeVisible();
  await expect(page.getByTestId("decision-row").first()).toBeVisible();
  await expect(page.getByTestId("stream-state")).toContainText("Connected");
  await expect(page.getByTestId("scenario-clock")).not.toHaveText("Loading");
  await expect(page.getByTestId("mode-strip")).toContainText("synthetic SGW data");

  await page.getByTestId("decision-row").filter({ hasText: "feeder 2207" }).click();
  await expect(page).toHaveURL(new RegExp(`d=${PS17}`));
  await sign(page);
  await expect(page.getByText("Signed. Waiting for the other team.")).toBeVisible();
  await expect(page.getByTestId("case-header")).toContainText("1 of 2");

  await switchUser(page, USER.waterLead);
  await page.getByTestId("decision-row").filter({ hasText: "feeder 2207" }).click();
  await sign(page);
  await expect(page.getByText("Signed. The decision is approved.")).toBeVisible();
  await page.getByRole("tab", { name: /Signatures/ }).click();
  await expect(page.getByTestId("approval-head")).toHaveText("Approved");

  expect(errors).toEqual([]);
});

test("keyboard: j and k move, Escape closes, Cmd+K jumps", async ({ page }) => {
  await login(page, USER.commander);
  await page.getByRole("tab", { name: /^All open/ }).click();
  const rows = page.getByTestId("decision-row");
  await expect(rows.first()).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("j");
  await expect(rows.nth(1)).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("k");
  await expect(rows.first()).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByText("Select a decision to see its details.")).toBeVisible();

  await page.keyboard.press("ControlOrMeta+k");
  await page.getByPlaceholder("Jump to decision or command").last().fill("forecast");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/forecast$/);
  await expect(page.getByRole("heading", { name: "Forecast", exact: true })).toBeVisible();
});

test("the sidebar collapses to a labelled rail with a hover tooltip", async ({ page }) => {
  await login(page, USER.commander);
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  const map = page.getByRole("link", { name: "Map", exact: true });
  await expect(map).toHaveAttribute("aria-label", "Map");
  await map.hover();
  await expect(page.getByRole("tooltip", { name: "Map" })).toBeVisible();
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
]) {
  test(`every InfoTip bubble stays inside the viewport and does not overflow at ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await login(page, USER.commander);
    await expect(page.getByTestId("decision-row").first()).toBeVisible();
    await expect(page.getByTestId("inspector")).toBeVisible();

    const triggers = page.locator('button[aria-label^="What does"], button[aria-label^="Approval:"]');
    const count = await triggers.count();
    expect(count).toBeGreaterThan(3);
    for (let i = 0; i < count; i++) {
      const trigger = triggers.nth(i);
      await trigger.scrollIntoViewIfNeeded();
      const box = await trigger.boundingBox();
      expect(box?.width, "trigger is a 20 px target").toBeGreaterThanOrEqual(19);
      await trigger.click();
      const bubble = page.locator('[data-testid^="infotip-"]');
      await expect(bubble).toBeVisible();
      const geometry = await bubble.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const textOut = Array.from(el.querySelectorAll("p, a")).filter((t) => {
          const b = t.getBoundingClientRect();
          return b.right > r.right + 0.5 || b.left < r.left - 0.5 || b.bottom > r.bottom + 0.5;
        }).length;
        return {
          left: r.left,
          top: r.top,
          right: r.right,
          bottom: r.bottom,
          width: r.width,
          overflowX: el.scrollWidth - el.clientWidth,
          textOut,
          vw: window.innerWidth,
          vh: window.innerHeight,
        };
      });
      expect(geometry.left, `tip ${i} left`).toBeGreaterThanOrEqual(0);
      expect(geometry.top, `tip ${i} top`).toBeGreaterThanOrEqual(0);
      expect(geometry.right, `tip ${i} right`).toBeLessThanOrEqual(geometry.vw);
      expect(geometry.bottom, `tip ${i} bottom`).toBeLessThanOrEqual(geometry.vh);
      expect(geometry.width, `tip ${i} width`).toBeLessThanOrEqual(281);
      expect(geometry.overflowX, `tip ${i} horizontal overflow`).toBeLessThanOrEqual(0);
      expect(geometry.textOut, `tip ${i} text outside the bubble`).toBe(0);
      await page.keyboard.press("Escape");
      await expect(bubble).toHaveCount(0);
    }
  });
}

test("an InfoTip closes on outside click and on scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 600 });
  await login(page, USER.commander);
  const trigger = page.getByRole("button", { name: "Info: Decision list" });
  const bubble = page.locator('[data-testid^="infotip-"]');
  await trigger.click();
  await expect(bubble).toBeVisible();
  await page.mouse.click(600, 300);
  await expect(bubble).toHaveCount(0);
  await trigger.click();
  await expect(bubble).toBeVisible();
  await page.evaluate(() => document.getElementById("main")?.scrollBy(0, 200));
  await expect(bubble).toHaveCount(0);
});

test("axe finds no serious violations on login and the home screen", async ({ page }) => {
  await page.goto("/login");
  const loginResults = await new AxeBuilder({ page }).analyze();
  expect(loginResults.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
  await login(page, USER.commander);
  await expect(page.getByTestId("decision-row").first()).toBeVisible();
  await expect(page.getByTestId("map").locator("canvas")).toBeVisible();
  const home = await new AxeBuilder({ page }).analyze();
  expect(home.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
});
