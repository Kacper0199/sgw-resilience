import { execFileSync } from "node:child_process";
import { DEMO_PASSWORD, USER } from "./support/login";

const ETR_TIME = "2024-09-28T18:00:00Z";

async function session(api: string, user: string): Promise<{ cookie: string; csrf: string } | null> {
  const login = await fetch(`${api}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ user_id: user, password: DEMO_PASSWORD }),
  });
  if (!login.ok) return null;
  const pairs = login.headers.getSetCookie().map((c) => c.split(";")[0]);
  const csrf = pairs.find((p) => p.startsWith("sgw_csrf="))?.split("=")[1] ?? "";
  return { cookie: pairs.join("; "), csrf };
}

/** Puts the private database back at the "signed" bookmark, waits for the private API, then moves the clock to the
 * ETR issue time (the global estimate is issued at 17:30Z). */
export default async function setup() {
  const db = process.env.SGW_E2E_DB ?? "";
  const api = process.env.SGW_E2E_API ?? "";
  if (!/^sgw_wp[a-z0-9_]+$/.test(db))
    throw new Error("SGW_E2E_DB must name a private builder database (sgw_wp...)");
  const run = (...args: string[]) =>
    execFileSync("uv", ["run", "sgw", ...args], { cwd: "..", stdio: "inherit" });
  run("demo", "goto", "signed", "-d", db, "--yes");
  run("api", "seed-users", "-d", db);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const s = await session(api, USER.dutyManager);
    if (s) {
      const headers = {
        cookie: s.cookie,
        "X-CSRF-Token": s.csrf,
        "content-type": "application/json",
        Origin: api,
      };
      const seek = await fetch(`${api}/api/scenario`, {
        method: "POST",
        headers,
        body: JSON.stringify({ action: "seek", scenario_time: ETR_TIME }),
      });
      const etr = seek.ok ? await fetch(`${api}/api/etr`, { headers: { cookie: s.cookie } }) : null;
      const body = etr?.ok ? ((await etr.json()) as { whole: unknown }) : null;
      if (body?.whole) return;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("the private API did not answer /api/etr at the ETR time after the database reset");
}
