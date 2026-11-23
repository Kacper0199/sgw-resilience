import { expect, type Page, test } from "@playwright/test";
import { login, switchUser, USER } from "./support/login";

/** Runs only through `scenario-ian.config.ts` against a private API (DEMO_MODE, SGW_DEMO_GOTO_DSN, scenario jobs and
 * injects on) and database. */

async function openMenu(page: Page) {
  await page.getByTestId("mode-strip").click();
  return page.getByTestId("scenario-menu");
}

async function loadScenario(page: Page, label: RegExp, title: string) {
  const menu = await openMenu(page);
  await menu.getByTestId("other-scenarios").getByRole("button", { name: label }).click();
  const dialog = page.getByTestId("load-scenario-dialog");
  await dialog.getByRole("button", { name: "Load scenario" }).click();
  await expect(dialog).toBeHidden({ timeout: 60_000 });
  await expect(page.getByText(`Loaded ${title}.`)).toBeVisible();
}

test("a presenter loads Hurricane Ian, other roles act on it, and Helene comes back unchanged", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, USER.commander);
  await expect(page.getByTestId("mode-strip")).toContainText("Replay of");
  await loadScenario(page, /^Hurricane Ian, September 2022/, "Hurricane Ian");
  await expect(page.getByTestId("mode-strip")).toContainText("Exercise of");
  await expect(page.getByTestId("mode-strip")).toContainText("scripted synthetic");
  await expect(page.getByTestId("scenario-clock")).toHaveText("11:00 ET (15:00Z)");
  await expect(
    page.getByText("Request 16 mutual-aid line crews from the Tidewater group").first(),
  ).toBeVisible({
    timeout: 20_000,
  });

  await page.goto("/brief");
  await expect(page.getByRole("heading", { name: "By team" })).toBeVisible();
  await expect(page.getByText("No outage report yet.").or(page.getByText(/customers out in/))).toBeVisible();
  await expect(page.getByRole("heading", { name: "Situation report" })).toHaveCount(0);
  await page.goto("/crews");
  await expect(page.getByText("Scripted", { exact: true })).toBeVisible();
  await expect(page.getByText("Saltgrass 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Damage photos/ })).toHaveCount(0);
  await page.goto("/water");
  await expect(page.getByText("Not modelled for this scenario")).toBeVisible();

  await switchUser(page, USER.logistics);
  await page.goto("/");
  await page.getByText("Send portable generator Petrel to Tidewrack Memorial hospital").first().click();
  await page.getByRole("button", { name: "Sign as Logistics" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Sign", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Sign as Logistics" })).toHaveCount(0);

  await switchUser(page, USER.auditor);
  await page.goto("/after-action");
  await expect(page.getByRole("heading", { name: "Deadlines" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "PSC report" })).toHaveCount(0);
  await page.goto("/health");
  await expect(page.getByText("No live feeds in this exercise.")).toBeVisible();

  await switchUser(page, USER.executive);
  await page.goto("/map");
  await expect(page.getByRole("button", { name: "Layers" })).toBeVisible();
  const menu = await openMenu(page);
  await expect(menu).toContainText("Hurricane Ian exercise");
  await expect(menu.getByTestId("other-scenarios").getByRole("button")).toHaveCount(0);
  await page.keyboard.press("Escape");

  await switchUser(page, USER.commander);
  await loadScenario(page, /^Hurricane Helene, September 2024/, "Hurricane Helene");
  await expect(page.getByTestId("mode-strip")).toContainText("Replay of");
  await expect(page.getByTestId("scenario-clock")).toHaveText("11:05 ET (15:05Z)");
  await page.goto("/");
  await expect(
    page.getByText("Request 12 mutual-aid line crews from the Prairie Lakes group").first(),
  ).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText("Tidewater")).toHaveCount(0);
  expect(errors).toEqual([]);
});
