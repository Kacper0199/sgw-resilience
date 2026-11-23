import { execFileSync } from "node:child_process";
import { DEMO_PASSWORD, USER } from "./support/login";

/** Puts the private database back at the "11 AM advisory" bookmark (a jump forward expires its decisions), then waits
 * until the private API answers from the recreated database. */
export default async function setup() {
  const db = process.env.SGW_E2E_DB ?? "";
  const api = process.env.SGW_E2E_API ?? "";
  if (!/^sgw_wp[a-z0-9_]+$/.test(db))
    throw new Error("SGW_E2E_DB must name a private builder database (sgw_wp...)");
  const run = (...args: string[]) =>
    execFileSync("uv", ["run", "sgw", ...args], { cwd: "..", stdio: "inherit" });
  run("demo", "goto", "at-n1", "-d", db, "--yes");
  run("api", "seed-users", "-d", db);
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const login = await fetch(`${api}/api/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user_id: USER.commander, password: DEMO_PASSWORD }),
    });
    const cookie = login.headers
      .getSetCookie()
      .map((c) => c.split(";")[0])
      .join("; ");
    const list = login.ok ? await fetch(`${api}/api/proposals`, { headers: { cookie } }) : null;
    if (list?.ok) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("the private API did not recover after the database reset");
}
