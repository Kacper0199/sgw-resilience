import { expect, type Page } from "@playwright/test";

/** The demo password the sign-in page prints in demo mode ("Demo password is 123. Demo only."). Mock mode accepts any non-empty password. */
export const DEMO_PASSWORD = "123";

export const USER = {
  commander: "ic_01",
  dutyManager: "ops_dm_01",
  dutyManagerRelief: "ops_dm_02",
  waterLead: "wtr_lead_01",
  waterCompliance: "wtr_comp_01",
  logistics: "log_01",
  etr: "plan_etr_01",
  executive: "exec_01",
  auditor: "audit_01",
  admin: "admin_01",
  dataOwner: "ml_01",
} as const;

export type LoginOptions = {
  password?: string;
  /** `form` types the user ID; `chooser` picks the person in the "Demo people" popover (demo mode only). */
  via?: "form" | "chooser";
  /** Runs on the sign-in page before anything is typed. */
  beforeSignIn?: (page: Page) => Promise<void>;
  /** Waits for the top band after the sign-in click; turn off for specs that assert on the sign-in page itself. */
  waitForShell?: boolean;
};

async function pickPerson(page: Page, userId: string) {
  await page.getByRole("button", { name: /^Demo people/ }).click();
  const option = page.locator(`[role="option"][data-user-id="${userId}"]`);
  if (!(await option.isVisible())) await page.getByRole("button", { name: /^Other accounts/ }).click();
  await option.click();
  await expect(page.getByLabel("User ID")).toHaveValue(userId);
}

/** Fills the sign-in form that is already on screen (also after "Switch user") and submits it. */
export async function signIn(
  page: Page,
  userId: string,
  { password = DEMO_PASSWORD, via = "form", waitForShell = true }: LoginOptions = {},
) {
  if (via === "chooser") await pickPerson(page, userId);
  else await page.getByLabel("User ID").fill(userId);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  if (waitForShell) await expect(page.getByTestId("top-band")).toBeVisible();
}

/** Opens /login and signs in as `userId` (default: the Incident Commander). */
export async function login(page: Page, userId: string = USER.commander, options: LoginOptions = {}) {
  await page.goto("/login");
  await options.beforeSignIn?.(page);
  await signIn(page, userId, options);
}

/** Opens the persona menu, chooses "Switch user" and signs in as another user. */
export async function switchUser(page: Page, userId: string, options: LoginOptions = {}) {
  await page.getByRole("button", { name: /Signed in as/ }).click();
  await page.getByRole("menuitem", { name: "Switch user" }).click();
  await signIn(page, userId, options);
}
