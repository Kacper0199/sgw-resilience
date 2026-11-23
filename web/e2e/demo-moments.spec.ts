import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

/** Runs only through `demo-moments.config.ts` against a private API (DEMO_MODE, SGW_DEMO_GOTO_DSN) and database. */

async function openMenu(page: Page) {
  await page.getByTestId("mode-strip").click();
  return page.getByTestId("scenario-menu");
}

test("a presenter plays the replay clock at 900x and pauses it", async ({ page }) => {
  await login(page, USER.commander);
  const clock = page.getByTestId("scenario-clock");
  await expect(clock).toHaveText("11:05 ET (15:05Z)");
  const controls = (await openMenu(page)).getByTestId("replay-controls");
  await controls.getByRole("button", { name: "900×" }).click();
  await expect(controls.getByRole("button", { name: "900×" })).toHaveAttribute("aria-pressed", "true");
  await expect(clock).not.toHaveText("11:05 ET (15:05Z)", { timeout: 15_000 });
  await controls.getByRole("button", { name: "Pause" }).click();
  await expect(controls.getByRole("button", { name: "Play" })).toBeVisible();
  const paused = await clock.textContent();
  await page.waitForTimeout(2500);
  await expect(clock).toHaveText(paused ?? "");
});

test("a presenter loads the morning after with its rule decisions, then the 11 AM advisory again", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, USER.commander);
  const menu = await openMenu(page);
  await menu
    .getByTestId("jump-list")
    .getByRole("button", { name: /^Morning after landfall/ })
    .click();
  const dialog = page.getByTestId("jump-dialog");
  await expect(dialog).toContainText("saved state");
  await dialog.getByRole("button", { name: "Load moment" }).click();
  await expect(dialog.getByRole("button", { name: /Loading/ })).toBeDisabled();
  await expect(dialog).toBeHidden({ timeout: 60_000 });
  await expect(page.getByText("Loaded Morning after landfall.")).toBeVisible();
  await expect(page.getByTestId("scenario-clock")).toHaveText("08:00 ET (12:00Z)");
  await expect(page.getByText("Send a potable water tanker to Tallowbranch hospital").first()).toBeVisible({
    timeout: 20_000,
  });

  const again = await openMenu(page);
  await again
    .getByTestId("jump-list")
    .getByRole("button", { name: /^11 AM advisory/ })
    .click();
  await dialog.getByRole("button", { name: "Load moment" }).click();
  await expect(dialog).toBeHidden({ timeout: 60_000 });
  await expect(page.getByTestId("scenario-clock")).toHaveText("11:05 ET (15:05Z)");
  expect(errors).toEqual([]);
});
