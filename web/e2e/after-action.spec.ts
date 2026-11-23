import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SHOTS = process.env.SGW_SHOTS ?? "test-results/shots";
const BROKEN_KEY = "sgw.mock.chain_broken_at";

const openReview = async (page: Page) => {
  await page.getByRole("link", { name: "After-action", exact: true }).click();
  await expect(page).toHaveURL(/\/after-action/);
  await expect(page.getByTestId("review-sentence")).toBeVisible();
};

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const contents = (page: Page) => page.getByRole("navigation", { name: "On this page" });
const goTo = (page: Page, name: string) => contents(page).getByRole("button", { name }).click();

test("the auditor reads what happened, which clocks were met and which break-glass uses need attention", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.auditor);
  await openReview(page);

  await expect(page.getByTestId("review-sentence")).toContainText("The audit log passed its check.");
  await expect(page.getByTestId("review-sentence")).toContainText("5 met, 2 missed, 1 still open");
  await expect(page.getByTestId("clock-row")).toHaveCount(8);
  await page.getByRole("button", { name: /^Missed/ }).click();
  await expect(page.getByTestId("clock-row")).toHaveCount(2);
  await expect(page.getByTestId("clock-row").first()).toContainText("36 m after the deadline");

  await goTo(page, "Emergency approvals");
  await expect(page).toHaveURL(/tab=break-glass/);
  await expect(contents(page).getByRole("button", { name: "Emergency approvals" })).toHaveAttribute(
    "aria-current",
    "location",
  );
  await expect(page.getByTestId("break-glass-row")).toHaveCount(2);
  await expect(page.getByTestId("break-glass-row").first()).toContainText("Co-signed late");
  await expect(page.getByTestId("break-glass-row").first()).toContainText("Approver unreachable");

  await goTo(page, "ETR accuracy");
  await expect(page.getByTestId("score-row").first()).toContainText("Whole service area");
  await expect(page.getByTestId("analog-line")).toContainText("1.5 h for the whole service area");

  await goTo(page, "Timeline");
  await expect(page.getByTestId("timeline-row").first()).toContainText("Decision proposed");
  await expect(page.getByTestId("untrusted-note")).toHaveCount(0);

  await goTo(page, "PSC report");
  await expect(page.getByTestId("sc-report")).toContainText("S.C. Code Ann. Regs. 103-314");
  await expect(page.getByTestId("sc-report")).toContainText("Draft, not filed");
  expect(errors).toEqual([]);
});

test("verify the ledger, then try a tampered copy: the first bad entry is named and the real ledger stays intact", async ({
  page,
}) => {
  await login(page, USER.auditor);
  await openReview(page);
  await page.getByRole("button", { name: "Check audit log", exact: true }).click();
  await expect(page.getByTestId("verify-result")).toContainText("The audit log passed its check");
  await page.getByRole("button", { name: "Run tamper test", exact: true }).click();
  await expect(page.getByTestId("tamper-result")).toContainText("The real audit log wasn't changed");
  await expect(page.getByTestId("tamper-result")).toContainText("The check fails at entry 702");
  await expect(page.getByTestId("verify-result")).toContainText("The audit log passed its check");
  await expect(page.getByTestId("review-sentence")).toContainText("The audit log passed its check.");
});

test("a ledger that does not verify is the first thing the page says and the report carries the notice", async ({
  page,
}) => {
  await login(page, USER.auditor);
  await page.evaluate((k) => sessionStorage.setItem(k, "702"), BROKEN_KEY);
  await openReview(page);
  await expect(page.getByTestId("review-sentence")).toHaveText(
    "The audit log fails its check from entry 702. Entries from there on can't be trusted.",
  );
  await expect(
    page.getByText(
      "Do not use: the audit log failed its check. Reports from this review carry this warning.",
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Check audit log", exact: true }).click();
  await expect(page.getByTestId("verify-result")).toContainText("The first bad entry is 702");
  await expect(page.getByTestId("untrusted-note")).toBeVisible();
  await expect(page.locator('[data-testid="timeline-row"][data-untrusted="true"]').first()).toContainText(
    "Not trusted",
  );
  await expect(page.getByTestId("sc-report")).toContainText("Do not use");
});

test("the review works from the keyboard", async ({ page }) => {
  await login(page, USER.auditor);
  await openReview(page);
  await contents(page).getByRole("button", { name: "Timeline" }).focus();
  await page.keyboard.press("Enter");
  await expect(contents(page).getByRole("button", { name: "Timeline" })).toHaveAttribute(
    "aria-current",
    "location",
  );
  await expect(page).toHaveURL(/tab=timeline/);
  await page.getByRole("button", { name: "Check audit log", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("verify-result")).toBeVisible();
});

test("a link with ?tab= opens at that section and decision ids link into Decisions", async ({ page }) => {
  await login(page, USER.auditor);
  await page.goto("/after-action?tab=timeline");
  await expect(page.getByTestId("timeline")).toBeInViewport();
  await page.goto("/after-action");
  const link = page.getByTestId("clock-row").first().getByRole("link", { name: "View decision" });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", /\/\?d=PRP-/);
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
]) {
  test(`every InfoTip on the review stays inside the viewport at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await login(page, USER.auditor);
    await openReview(page);
    await page.getByRole("button", { name: "Check audit log", exact: true }).click();
    await expect(page.getByTestId("verify-result")).toBeVisible();
    const triggers = page.locator('button[aria-label^="What does"]');
    const count = await triggers.count();
    expect(count).toBeGreaterThanOrEqual(8);
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
      expect(box.left, `tip ${i} left`).toBeGreaterThanOrEqual(0);
      expect(box.top, `tip ${i} top`).toBeGreaterThanOrEqual(0);
      expect(box.right, `tip ${i} right`).toBeLessThanOrEqual(box.vw);
      expect(box.bottom, `tip ${i} bottom`).toBeLessThanOrEqual(box.vh);
      await page.keyboard.press("Escape");
      await expect(bubble).toHaveCount(0);
    }
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`axe finds no serious violations on the review (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.auditor);
    await openReview(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.getByRole("button", { name: "Check audit log", exact: true }).click();
    await page.getByRole("button", { name: "Run tamper test", exact: true }).click();
    await expect(page.getByTestId("tamper-result")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);
  });
}

test("after-action: screenshots for the review", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, USER.auditor);
  await openReview(page);
  await page.getByRole("button", { name: "Check audit log", exact: true }).click();
  await expect(page.getByTestId("verify-result")).toBeVisible();
  for (const [w, h] of [
    [1440, 900],
    [1920, 1080],
  ] as const) {
    await page.setViewportSize({ width: w, height: h });
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      for (const [name, slug] of [
        ["Status and numbers", "top"],
        ["Deadlines", "deadlines"],
        ["Emergency approvals", "emergency"],
        ["ETR accuracy", "accuracy"],
        ["Timeline", "timeline"],
        ["PSC report", "report"],
      ] as const) {
        await goTo(page, name);
        await page.waitForTimeout(500);
        await page.screenshot({ path: `${SHOTS}/after-action-${slug}-${w}-${theme}.png` });
      }
    }
  }
});
