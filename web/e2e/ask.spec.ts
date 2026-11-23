import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SHOTS = process.env.SGW_SHOTS ?? "test-results/shots";

const openAsk = async (page: Page) => {
  await page.getByRole("link", { name: "Ask AI", exact: true }).click();
  await expect(page).toHaveURL(/\/ask/);
  await expect(page.getByTestId("starters")).toBeVisible();
};

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const send = async (page: Page, text: string) => {
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();
  const box = page.getByRole("textbox", { name: "Ask about the storm response" });
  await box.fill(text);
  await box.press("Enter");
};

test("a question runs through its specialists to a sourced answer, and a badge opens the passage", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.commander);
  await openAsk(page);
  await page.getByRole("button", { name: /revise a global ETR/ }).click();

  await expect(page.getByRole("region", { name: "Working on an answer…" })).toBeVisible();
  await expect(page.getByTestId("steps")).toHaveCount(1);

  const answer = page.getByTestId("answer-text");
  await expect(answer).toBeVisible({ timeout: 8000 });
  await expect(page.getByRole("region", { name: "Working on an answer…" })).toHaveCount(0);
  await expect(answer.getByTestId("source-badge")).toHaveCount(1);

  await answer.getByTestId("source-badge").first().click();
  const card = page.getByTestId("source-card").first();
  await expect(card).toHaveAttribute("data-active", "true");
  await expect(card).toContainText("DOM 14.206 Rev K");
  await expect(card).toContainText("Revise a published ETR");
  expect(errors).toEqual([]);
});

test("the copilot says when something is not in the documents, and shows what was unverified", async ({
  page,
}) => {
  await login(page, USER.commander);
  await openAsk(page);
  await send(page, "What is our 2025 vegetation management budget?");
  await expect(page.getByTestId("abstain")).toContainText("I couldn't find this", { timeout: 8000 });
  await expect(page.getByRole("complementary", { name: "Sources" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sources" })).toHaveCount(0);

  await send(page, "Any new tickets?");
  await expect(page.getByText(/Uses an unverified field report/)).toBeVisible({ timeout: 8000 });
  await expect(page.getByTestId("source-card").first()).toContainText("Unverified field report");

  await send(page, "What do the procedures say about paper tickets?");
  await expect(page.getByTestId("findings-only")).toContainText("failed its source check", { timeout: 8000 });
});

test("photos, page links and suggested questions render inline, and a photo opens its detail", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.commander);
  await openAsk(page);
  await send(page, "Show me the photos of the flooded area");
  const strip = page.getByTestId("answer-photos");
  await expect(strip).toBeVisible({ timeout: 8000 });
  await expect(strip.getByTestId("answer-photo")).toHaveCount(4);
  await expect(page.getByTestId("answer-link").first()).toHaveAttribute("href", "/crews?tab=photos");
  await strip.getByTestId("answer-photo").first().click();
  await expect(page.getByTestId("photo-preview")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Which crews can reach these?" }).click();
  await expect(page.getByTestId("turn")).toHaveCount(2, { timeout: 8000 });
  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(page.getByTestId("starters")).toBeVisible();
  expect(errors).toEqual([]);
});

test("an unrelated question gets a helpful reply with three questions to try", async ({ page }) => {
  await login(page, USER.commander);
  await openAsk(page);
  await send(page, "What is the weather in Paris?");
  await expect(page.getByTestId("answer-text")).toContainText("outside what I can help with", {
    timeout: 8000,
  });
  await expect(page.getByTestId("question-chips").getByRole("button")).toHaveCount(3);
  await expect(page.getByText(/Not found/)).toHaveCount(0);
});

test("ids in an answer are chips that open the page showing them", async ({ page }) => {
  await login(page, USER.commander);
  await openAsk(page);
  await page.getByRole("button", { name: /PS-17's deadline/ }).click();
  const answer = page.getByTestId("answer-text");
  await expect(answer).toBeVisible({ timeout: 8000 });
  await expect(answer.getByTestId("ref-chip")).toHaveText([
    "latest advisory",
    "PS-17",
    "Hook up the portable generator at PS-17",
    "Dispatch the fuel truck to PS-17",
  ]);
  await expect(answer).not.toContainText("DC-");
  await answer.getByRole("link", { name: /^PS-17/ }).hover();
  await expect(page.getByRole("tooltip")).toContainText("Cedarfall pump station");
  await answer.getByRole("link", { name: /^Hook up the portable generator/ }).click();
  await expect(page).toHaveURL(/\/\?d=PRP-PS17-FDR2207-PRIO/);
});

test("Runs keeps how each answer was built, and a run can be asked again", async ({ page }) => {
  await login(page, USER.commander);
  await openAsk(page);
  await page.getByRole("button", { name: /pump stations have their own generator/ }).click();
  await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
  await page.getByRole("button", { name: /Show steps/ }).click();
  await expect(page.getByRole("list", { name: "Steps" })).toContainText("Checked water status");
  await page.getByRole("button", { name: "Step details" }).click();
  await expect(page).toHaveURL(/tab=runs/);
  const detail = page.getByTestId("run-detail");
  await expect(detail.getByRole("list", { name: "Plan" }).getByRole("listitem")).toHaveCount(3);
  await expect(detail.getByRole("table", { name: "Step details" })).toContainText("Checked water status");
  await detail.getByRole("button", { name: "Ask again" }).click();
  await expect(page.getByTestId("user-message")).toHaveCount(2, { timeout: 8000 });
  await expect(page.getByTestId("answer-text")).toHaveCount(2, { timeout: 8000 });
});

test("it is keyboard-only usable: Enter sends, Stop is reachable, badges are buttons", async ({ page }) => {
  await login(page, USER.commander);
  await openAsk(page);
  await page.getByRole("textbox", { name: "Ask about the storm response" }).focus();
  await page.keyboard.type("When do I have to revise a global ETR?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Stop response" })).toBeVisible();
  await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
  await page.getByTestId("source-badge").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("source-card").first()).toHaveAttribute("data-active", "true");
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
]) {
  test(`every InfoTip on Ask AI stays inside the viewport at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await login(page, USER.commander);
    await openAsk(page);
    await page.getByRole("button", { name: /revise a global ETR/ }).click();
    await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
    const triggers = page.locator(
      'main button[aria-label^="What does"]:visible, main button[aria-label^="Info:"]:visible',
    );
    const count = await triggers.count();
    expect(count).toBeGreaterThanOrEqual(3);
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
  test(`axe finds no serious violations on Ask AI, chat and runs (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.commander);
    await openAsk(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const serious = async () =>
      (await new AxeBuilder({ page }).analyze()).violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
    expect(await serious()).toEqual([]);
    await send(page, "Any new tickets?");
    await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
    await send(page, "What is our 2025 vegetation management budget?");
    await expect(page.getByTestId("abstain")).toBeVisible({ timeout: 8000 });
    expect(await serious()).toEqual([]);
    await page.getByRole("button", { name: "Show chat history" }).click();
    await page
      .getByRole("button", { name: /Show steps/ })
      .first()
      .click();
    expect(await serious()).toEqual([]);
    await page.getByRole("button", { name: /^Activity/ }).click();
    await expect(page.getByTestId("run-detail")).toBeVisible();
    expect(await serious()).toEqual([]);
  });
}

test("the screen reads in grayscale: states carry words and shapes, never colour alone", async ({ page }) => {
  await login(page, USER.commander);
  await openAsk(page);
  await send(page, "Any new tickets?");
  await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
  await page.addStyleTag({ content: "html { filter: grayscale(1); }" });
  await expect(page.getByText(/Uses an unverified field report/)).toBeVisible();
  await expect(page.getByTestId("source-card").first()).toContainText("Unverified field report");
  await page.screenshot({ path: `${SHOTS}/ask-1440-gray.png` });
});

test("the copilot refuses nothing it cannot do: the composer states it is read-only", async ({ page }) => {
  await login(page, USER.executive);
  await openAsk(page);
  await expect(page.getByText("AI can make mistakes. Check the sources before you act.")).toBeVisible();
  await page.getByRole("button", { name: 'What does "Read-only" mean?' }).click();
  await expect(page.getByTestId("infotip-read_only")).toContainText("can't sign, send");
});

test("every icon says what it does on hover, New conversation appears with the first answer, and Sources opens by itself and stays closed once closed", async ({
  page,
}) => {
  await login(page, USER.commander);
  await openAsk(page);
  await expect(page.getByRole("button", { name: "New conversation" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sources" })).toHaveCount(0);
  const tip = async (name: string, nth = 0) => {
    await page.getByRole("button", { name, exact: true }).nth(nth).hover();
    const bubble = page.getByRole("tooltip").filter({ hasText: name });
    await expect(bubble).toBeVisible();
    const box = await page
      .locator('[data-slot="tooltip"], [data-radix-popper-content-wrapper]')
      .last()
      .boundingBox();
    const vp = page.viewportSize();
    if (box && vp) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
      expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
    }
    await page.mouse.move(700, 600, { steps: 10 });
    await expect(page.getByRole("tooltip")).toHaveCount(0);
  };
  await tip("Show chat history");
  await page.getByRole("button", { name: /revise a global ETR/ }).click();
  await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
  await expect(page.getByRole("complementary", { name: "Sources" })).toBeVisible();
  await expect(page.getByRole("button", { name: "2 sources" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New conversation" })).toHaveCount(1);
  for (const name of ["Copy answer", "Helpful", "Not helpful", "Ask again", "More"]) await tip(name);
  await tip("Hide sources");
  await page.getByRole("button", { name: "Hide sources" }).first().click();
  await expect(page.getByRole("complementary", { name: "Sources" })).toHaveCount(0);
  await send(page, "Which of our Aiken pump stations have their own generator?");
  await expect(page.getByTestId("answer-text")).toHaveCount(2, { timeout: 8000 });
  await expect(page.getByRole("complementary", { name: "Sources" })).toHaveCount(0);
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Sources" })).toBeVisible();
  await page.getByRole("button", { name: "Show chat history" }).click();
  await expect(page.getByRole("complementary", { name: "Chat history" })).toContainText("When do I have to");
  await expect(page.getByRole("button", { name: "New conversation" })).toHaveCount(1);
});

test("on a phone the sources open as a sheet from the answer", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("sgw.sidebar", "collapsed"));
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, USER.commander);
  await page.goto("/ask");
  await expect(page.getByTestId("starters")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ask-empty-390-light.png` });
  await page.getByRole("button", { name: /revise a global ETR/ }).click();
  await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
  await expect(page.getByRole("complementary", { name: "Sources" })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/ask-answer-390-light.png` });
  await page.getByRole("button", { name: "2 sources" }).click();
  await expect(page.getByRole("dialog")).toContainText("DOM 14.206 Rev K");
  await page.screenshot({ path: `${SHOTS}/ask-sources-390-light.png` });
});

for (const theme of ["light", "dark"] as const) {
  for (const width of [1440, 1920]) {
    test(`screens at ${width} (${theme})`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
      await page.setViewportSize({ width, height: width === 1920 ? 1080 : 900 });
      await login(page, USER.commander);
      await openAsk(page);
      await page.screenshot({ path: `${SHOTS}/ask-empty-${width}-${theme}.png` });
      await page.getByRole("button", { name: /revise a global ETR/ }).click();
      await expect(page.getByTestId("answer-text")).toBeVisible({ timeout: 8000 });
      await page.getByRole("button", { name: /Show steps/ }).click();
      await page.getByTestId("source-badge").first().click();
      await page.mouse.move(700, 600);
      await page.screenshot({ path: `${SHOTS}/ask-answer-${width}-${theme}.png` });
      await page.getByRole("button", { name: "Show chat history" }).click();
      await page.getByRole("button", { name: "Hide sources" }).first().hover();
      await expect(page.getByRole("tooltip")).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/ask-history-${width}-${theme}.png` });
    });
  }
}
