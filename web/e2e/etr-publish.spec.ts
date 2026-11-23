import { expect, type Page, test } from "@playwright/test";
import { DEMO_PASSWORD, login, switchUser, USER } from "./support/login";

/**
 * D4 global ETR on a private API: the ETR planner drafts it on Forecast → Restoration times, Command and Operations
 * sign it on the decision card, the planner publishes it, and After-action shows the published estimate. Every step
 * goes through the browser; the clock was moved to the ETR time by the global setup.
 */

async function signOnCard(page: Page, proposalHref: string) {
  await page.goto(proposalHref);
  const sign = page.getByRole("button", { name: /^Sign as / });
  await expect(sign).toBeEnabled({ timeout: 20_000 });
  await sign.click();
  await page.getByRole("dialog").getByRole("button", { name: "Sign", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("planner drafts, Command and Operations sign, planner publishes, After-action shows it", async ({
  page,
}) => {
  let href = "";

  await test.step("the planner drafts the global ETR", async () => {
    await login(page, USER.etr, { password: DEMO_PASSWORD });
    await page.goto("/forecast?tab=etr");
    const tab = page.getByTestId("restoration-tab");
    await expect(tab).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("etr-row")).toHaveCount(11);
    await tab.getByRole("button", { name: "Draft global ETR" }).click();
    await expect(tab.getByText("Waiting for Command and Operations to sign.")).toBeVisible({
      timeout: 60_000,
    });
    href = (await tab.getByRole("link", { name: /View decision/ }).getAttribute("href")) ?? "";
    expect(href).toMatch(/^\/\?d=PRP-/);
  });

  await test.step("others see the state without controls", async () => {
    await switchUser(page, USER.commander, { password: DEMO_PASSWORD });
    await page.goto("/forecast?tab=etr");
    const tab = page.getByTestId("restoration-tab");
    await expect(tab.getByText("Waiting for Command and Operations to sign.")).toBeVisible({
      timeout: 20_000,
    });
    await expect(tab.getByRole("button", { name: /Draft global ETR|Publish/ })).toHaveCount(0);
  });

  await test.step("Command signs", async () => {
    await signOnCard(page, href);
  });

  await test.step("Operations signs", async () => {
    await switchUser(page, USER.dutyManager, { password: DEMO_PASSWORD });
    await signOnCard(page, href);
  });

  await test.step("the planner publishes", async () => {
    await switchUser(page, USER.etr, { password: DEMO_PASSWORD });
    await page.goto("/forecast?tab=etr");
    const tab = page.getByTestId("restoration-tab");
    await tab.getByRole("button", { name: "Publish" }).click({ timeout: 20_000 });
    await expect(tab.getByText(/^Published .* by ETR Specialist\.$/)).toBeVisible({ timeout: 60_000 });
    await expect(tab.getByRole("button", { name: /Draft global ETR|Publish/ })).toHaveCount(0);
  });

  await test.step("After-action shows the published estimate", async () => {
    await switchUser(page, USER.auditor, { password: DEMO_PASSWORD });
    await page.goto("/after-action?tab=scorecard");
    const block = page.getByTestId("published-etr");
    await expect(block).toBeVisible({ timeout: 20_000 });
    await expect(block).toContainText("signed by Command and Operations");
    await expect(page.getByText("Accuracy is known once power is restored.")).toBeVisible();
  });
});
