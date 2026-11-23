import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

/** Runs only through `scenario-jump.config.ts` against a private API and database (never the shared stack). */

async function jump(page: Page, label: RegExp, movedTo: string) {
  await page.getByTestId("mode-strip").click();
  const menu = page.getByTestId("scenario-menu");
  await menu.getByTestId("jump-list").getByRole("button", { name: label }).click();
  const dialog = page.getByTestId("jump-dialog");
  await expect(dialog).toContainText("signatures are voided");
  await dialog.getByRole("button", { name: /^Jump/ }).click();
  await expect(dialog).toBeHidden({ timeout: 30_000 });
  await expect(page.getByText(`Replay moved to ${movedTo}.`)).toBeVisible();
}

test("a presenter jumps to a demo moment: the clock and the decision queue follow, then jumps back", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, USER.commander);
  const clock = page.getByTestId("scenario-clock");
  await expect(clock).toHaveText("11:05 ET (15:05Z)");
  const rows = page.getByTestId("decision-row");
  await expect(rows.first()).toBeVisible();

  await jump(page, /^Restoration estimate published/, "Sep 28, 14:00 ET");
  await expect(clock).toHaveText("14:00 ET (18:00Z)");
  await expect(page.getByTestId("stream-state")).toContainText("Connected");
  await expect(rows).toHaveCount(0);
  await expect(page.getByText("No open decisions match these filters.")).toBeVisible();

  await jump(page, /^11 AM advisory/, "Sep 26, 11:05 ET");
  await expect(clock).toHaveText("11:05 ET (15:05Z)");
  expect(errors).toEqual([]);
});

test("a role that cannot move the clock sees the scenario but no jump", async ({ page }) => {
  await login(page, USER.admin);
  await page.getByTestId("mode-strip").click();
  const menu = page.getByTestId("scenario-menu");
  await expect(menu.getByTestId("scenario-period")).toHaveText("23 Sep – 6 Oct 2024, Eastern time");
  await expect(menu.getByTestId("data-sources")).toBeVisible();
  await expect(menu.getByTestId("jump-list")).toHaveCount(0);
  await expect(menu.getByText("Jump to")).toHaveCount(0);
});
