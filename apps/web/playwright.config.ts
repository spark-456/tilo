import { defineConfig, devices } from "@playwright/test";

// P0-08a acceptance tests (PRD 18.2/18.3/9.7/17.5). Run with
// `pnpm --filter @tilo/web exec playwright test`.
//
// Locally this uses the installed Microsoft Edge (channel "msedge") so no
// separate browser download is needed; CI sets CI=true and installs/uses
// plain Chromium via `playwright install chromium` (per the ticket's Windows
// note and PRD 17.5 "full support: current and previous Chrome and Edge").
//
// TILO_WEB_PORT gives each worktree its own dev server; with a shared port,
// reuseExistingServer would silently test another worktree's code.
const PORT = Number(process.env.TILO_WEB_PORT ?? 5173);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const BROWSER = { ...devices["Desktop Chrome"], channel: process.env.CI ? undefined : "msedge" };
const TIMING_SPECS = [
  "**/world-perf.spec.ts",
  "**/world-reduced-motion-toggle.spec.ts",
  "**/stage-camera-freeze.spec.ts",
];

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: "list",
  use: {
    // 127.0.0.1, not "localhost": Vite's dev server binds IPv6 ([::1]) only by
    // default, which on some Windows setups isn't reachable via the "localhost"
    // name, hanging the webServer readiness check.
    baseURL: ORIGIN,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: TIMING_SPECS,
      use: BROWSER,
    },
    {
      // Frame-rate and frame-timing measurements run one at a time after everything else, so
      // the parallel suite's own CPU load is not what they measure.
      name: "timing",
      testMatch: TIMING_SPECS,
      dependencies: ["chromium"],
      workers: 1,
      use: BROWSER,
    },
  ],
  webServer: {
    command: `pnpm exec vite --host 127.0.0.1 --port ${PORT} --strictPort`,
    // Vite's own client script, not "/": it 200s as soon as the dev server is
    // up, even before apps/web has an index.html — so readiness reflects
    // "the dev server started", and a missing app surfaces as each test's own
    // failure (e.g. a selector not found) instead of one opaque global
    // webServer timeout.
    url: `${ORIGIN}/@vite/client`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
