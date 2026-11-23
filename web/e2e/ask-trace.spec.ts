import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const QUESTION = "Which Aiken surge needs a crew, and what do the photos and gauge show?";

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function askSurge(page: Page) {
  await page.getByRole("link", { name: "Ask AI", exact: true }).click();
  await expect(page.getByTestId("starters")).toBeVisible();
  const box = page.getByRole("textbox", { name: "Ask about the storm response" });
  await box.fill(QUESTION);
  await box.press("Enter");
  await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 10_000 });
}

const scrollOffenders = (page: Page) =>
  page.evaluate(() => {
    const sheet = document.querySelector('[data-testid="trace-sheet"]');
    if (!sheet) return ["no sheet"];
    return [sheet, ...sheet.querySelectorAll("*")]
      .filter((el) => {
        const s = getComputedStyle(el);
        const scrolls = (o: string, scroll: number, client: number) =>
          ["auto", "scroll"].includes(o) && scroll - client > 1;
        const y =
          scrolls(s.overflowY, el.scrollHeight, el.clientHeight) && !el.closest("[data-scroll-region]");
        return y || scrolls(s.overflowX, el.scrollWidth, el.clientWidth);
      })
      .map((el) => `${el.tagName}.${String(el.className).slice(0, 40)}`);
  });

for (const user of [USER.admin, USER.auditor, USER.dataOwner]) {
  test(`${user} opens how the answer was made from the More menu`, async ({ page }) => {
    const errors = collectErrors(page);
    await login(page, user);
    await askSurge(page);
    await page.getByRole("button", { name: "More" }).click();
    await expect(page.getByRole("menuitem", { name: "Step details in Activity" })).toHaveCount(0);
    await page.getByRole("menuitem", { name: "How this answer was made" }).click();

    const sheet = page.getByTestId("trace-sheet");
    await expect(sheet.getByRole("heading", { name: "How this answer was made" })).toBeVisible();
    await expect(page).toHaveURL(/trace=run-mock-/);
    await expect(sheet.getByTestId("trace-totals")).toContainText("AI calls");
    await expect(sheet.getByTestId("trace-lane")).toHaveCount(3);
    await expect(sheet.getByTestId("trace-phase")).toHaveCount(6);
    await expect(sheet.getByTestId("trace-tool").filter({ hasText: "Refused" })).toHaveCount(1);
    expect(await scrollOffenders(page)).toEqual([]);

    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(page).not.toHaveURL(/trace=/);
    expect(errors).toEqual([]);
  });
}

test("operations keeps the folded step line and sees no trace", async ({ page }) => {
  await login(page, USER.dutyManager);
  await askSurge(page);
  await page.getByRole("button", { name: "More" }).click();
  await expect(page.getByRole("menuitem", { name: "How this answer was made" })).toHaveCount(0);
  await expect(page.getByRole("menuitem", { name: "Step details in Activity" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("steps")).toBeVisible();

  await page.goto("/ask?trace=run-mock-1");
  await expect(page.getByTestId("trace-sheet")).toHaveCount(0);
  await page.goto("/health?tab=runs&trace=RUN-0047");
  await expect(page.getByTestId("trace-sheet")).toHaveCount(0);
});

test("System health opens the same sheet from a request row", async ({ page }) => {
  await login(page, USER.admin);
  await page.goto("/health?tab=runs");
  const run = page.getByTestId("agent-run-row").nth(1);
  await run.getByRole("button", { name: /How request RUN-0047 was made/ }).click();
  const sheet = page.getByTestId("trace-sheet");
  await expect(sheet.getByTestId("trace-lane")).toHaveCount(3);
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(run.getByRole("button", { name: /How request RUN-0047 was made/ })).toBeFocused();
});

test("a run from today's graph opens as a flat list", async ({ page }) => {
  await login(page, USER.admin);
  await page.goto("/health?tab=runs&trace=RUN-0048");
  const sheet = page.getByTestId("trace-sheet");
  await expect(sheet.getByTestId("trace-phase").first()).toBeVisible();
  await expect(sheet.getByTestId("trace-lane")).toHaveCount(0);
});

test("the new chips open the page that shows them", async ({ page }) => {
  await login(page, USER.dutyManager);
  await askSurge(page);
  const answer = page.getByTestId("answer-text");
  await expect(answer.getByTestId("ref-chip")).toHaveCount(7);
  const targets = {
    surge: /\/map\?county=45003&at=2024-09-27T04%3A00%3A00Z/,
    photo: /\/crews\?photo=LADI-0042/,
    gauge: /\/map\?gauge=02197000/,
    crew: /\/crews\?crew=CRW-AIK-04/,
    yard: /\/crews\?yard=STG-AIK-SANDHILL-YARD/,
  } as const;
  for (const [kind, url] of Object.entries(targets)) {
    await page.goto("/ask");
    await askSurge(page);
    await page.getByTestId("answer-text").locator(`[data-kind="${kind}"]`).click();
    await expect(page).toHaveURL(url);
  }
});

test("the zone chip opens Water on that zone and the check chip opens Readiness on that check", async ({
  page,
}) => {
  await login(page, USER.dutyManager);
  await askSurge(page);
  await page.getByTestId("answer-text").locator('[data-kind="zone"]').click();
  await expect(page).toHaveURL(/\/water\?zone=WZ-PS17-CEDARFALL/);
  const zone = page.locator('tr[data-row-id="WZ-PS17-CEDARFALL"]');
  await expect(zone).toHaveAttribute("data-focused", "true");
  await expect(zone.getByRole("button", { name: "Collapse row" })).toBeVisible();

  await page.goto("/ask");
  await askSurge(page);
  await page.getByTestId("answer-text").locator('[data-kind="check"]').click();
  await expect(page).toHaveURL(/\/readiness\?check=DC-RDY-GEN-PS52-LOADTEST/);
  const check = page.locator('tr[data-row-id="DC-RDY-GEN-PS52-LOADTEST"]');
  await expect(check).toHaveAttribute("data-focused", "true");
  await expect(check).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("complementary", { name: "Check details" })).toContainText("Annual load test");
});

test("a zone or check far down the list is scrolled into view", async ({ page }) => {
  await login(page, USER.dutyManager);
  await page.goto("/water?zone=WZ-PS52-DEERWATER");
  const zone = page.locator('tr[data-row-id="WZ-PS52-DEERWATER"]');
  await expect(zone).toHaveAttribute("data-focused", "true");
  await expect(zone).toBeInViewport({ ratio: 1 });

  await page.goto("/readiness?check=DC-RDY-TANKER-TALLOWBRANCH");
  const check = page.locator('tr[data-row-id="DC-RDY-TANKER-TALLOWBRANCH"]');
  await expect(check).toHaveAttribute("data-focused", "true");
  await expect(check).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole("complementary", { name: "Check details" })).toContainText(
    "Standby potable-water tanker",
  );
});

for (const theme of ["light", "dark"] as const) {
  test(`the trace sheet has no serious accessibility violations (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.admin);
    await page.goto("/health?tab=runs&trace=RUN-0047");
    await expect(page.getByTestId("trace-lane")).toHaveCount(3);
    await page
      .getByTestId("trace-sheet")
      .evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
}
