import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.SGW_E2E_PORT ?? 61800);

/** The live G1 story against the running stack: Vite in development mode (no mocks) proxies /api to the API on 127.0.0.1:8080. */
export default defineConfig({
  testDir: ".",
  testMatch: /thin-slice\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1440, height: 900 } },
  webServer: {
    command: `pnpm exec vite --port ${PORT} --strictPort`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
