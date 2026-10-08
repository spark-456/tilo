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
// CP2 (`just e2e-cp2`, TILO_CP2=1): the project "cp2" walks the real dev API (`just dev-api`
// equivalent: fake Director and runner, in-memory store, no credentials) through its own Vite
// server that has VITE_TILO_API_URL set. The API's address is fixed at 127.0.0.1:8080 (its Host
// check). CI never sets TILO_CP2, so it starts neither server.
const CP2 = process.env.TILO_CP2 === "1";
const CP2_PORT = Number(process.env.TILO_CP2_PORT ?? 5391);
const CP2_ORIGIN = `http://127.0.0.1:${CP2_PORT}`;
const CP2_API = "http://127.0.0.1:8080";
const CP2_SPECS = "**/cp2/**";
// NFR-01 (`TILO_NFR01=1`, local only): the landing-page budget is measured on the production build
// served by `vite preview`, with the network and CPU throttled for the phone case. CI never sets it.
const NFR01 = process.env.TILO_NFR01 === "1";
const NFR01_PORT = Number(process.env.TILO_NFR01_PORT ?? 5393);
const NFR01_ORIGIN = `http://127.0.0.1:${NFR01_PORT}`;
const NFR01_SPECS = "**/nfr01/**";
// WEB-PARITY (`TILO_PARITY=1`, `just parity`, local only): the Park pixel-parity harness. Its own Vite
// app server (TILO_PARITY_PORT) is ours; the design reference is served by the spec itself on
// TILO_PARITY_REF_PORT. Never the shared 5173. CI never sets TILO_PARITY.
const PARITY = process.env.TILO_PARITY === "1";
const PARITY_PORT = Number(process.env.TILO_PARITY_PORT ?? 5395);
const PARITY_ORIGIN = `http://127.0.0.1:${PARITY_PORT}`;
const PARITY_SPECS = "**/park/parity/**";
// LIVE (`TILO_LIVE=1`, local only): the Park decisions flow against the live Api (WIRE-3). A tiny fake tilo-api
// (e2e/support/fakeCardsApi.mjs: GET /worlds, GET /cards, the answer route, a control surface) and its own Vite server
// with VITE_TILO_API_URL set, both on private ports. No credentials, no real backend. CI never sets TILO_LIVE.
const LIVE = process.env.TILO_LIVE === "1";
const LIVE_PORT = Number(process.env.TILO_LIVE_PORT ?? 5397);
const LIVE_API_PORT = Number(process.env.TILO_LIVE_API_PORT ?? 5398);
const LIVE_ORIGIN = `http://127.0.0.1:${LIVE_PORT}`;
const LIVE_API = `http://127.0.0.1:${LIVE_API_PORT}`;
const LIVE_SPECS = "**/live/**";
// FR-WLD-13 (`TILO_PERF_PHONE=1`, local only): the phone frame-rate measurement runs on the production build
// served by `vite preview`, on its own private port. CI never sets it.
const PERF_PHONE = process.env.TILO_PERF_PHONE === "1";
const PERF_PHONE_PORT = Number(process.env.TILO_PERF_PHONE_PORT ?? 5321);
const PERF_PHONE_ORIGIN = `http://127.0.0.1:${PERF_PHONE_PORT}`;
const PERF_PHONE_SPECS = "**/world-perf-phone.spec.ts";
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
      testIgnore: [
        ...TIMING_SPECS,
        PERF_PHONE_SPECS,
        CP2_SPECS,
        NFR01_SPECS,
        PARITY_SPECS,
        LIVE_SPECS,
      ],
      // Runs the timing project after this one finishes, pass or fail. A `dependencies` link would
      // skip the C8 freeze and perf specs whenever any chromium test failed.
      teardown: "timing",
      use: BROWSER,
    },
    {
      // Frame-rate and frame-timing measurements run one at a time after everything else, so
      // the parallel suite's own CPU load is not what they measure. Chromium's `teardown` starts
      // it, so `--project=timing` alone also works (CI can run it as its own step), and `--no-deps` runs
      // just the filtered specs without it.
      name: "timing",
      testMatch: TIMING_SPECS,
      workers: 1,
      use: BROWSER,
    },
    ...(CP2
      ? [{ name: "cp2", testMatch: CP2_SPECS, use: { ...BROWSER, baseURL: CP2_ORIGIN } }]
      : []),
    ...(LIVE
      ? [
          {
            name: "live",
            testMatch: LIVE_SPECS,
            workers: 1,
            use: { ...BROWSER, baseURL: LIVE_ORIGIN },
          },
        ]
      : []),
    ...(PERF_PHONE
      ? [
          {
            name: "perf-phone",
            testMatch: PERF_PHONE_SPECS,
            workers: 1,
            use: { ...BROWSER, baseURL: PERF_PHONE_ORIGIN },
          },
        ]
      : []),
    ...(NFR01
      ? [{ name: "nfr01", testMatch: NFR01_SPECS, use: { ...BROWSER, baseURL: NFR01_ORIGIN } }]
      : []),
    ...(PARITY
      ? [
          {
            name: "parity",
            testMatch: "**/park/parity/*.spec.ts",
            workers: 1,
            timeout: 180_000,
            // Grayscale glyph anti-aliasing on both sides (LCD text and hinting are most of the AA noise).
            use: {
              ...BROWSER,
              baseURL: PARITY_ORIGIN,
              launchOptions: { args: ["--disable-lcd-text", "--font-render-hinting=none"] },
            },
          },
        ]
      : []),
  ],
  webServer: [
    ...(NFR01
      ? [
          {
            command: `pnpm exec vite build && pnpm exec vite preview --host 127.0.0.1 --port ${NFR01_PORT} --strictPort`,
            url: `${NFR01_ORIGIN}/`,
            reuseExistingServer: false,
            timeout: 240_000,
          },
        ]
      : []),
    ...(PERF_PHONE
      ? [
          {
            command: `pnpm exec vite build && pnpm exec vite preview --host 127.0.0.1 --port ${PERF_PHONE_PORT} --strictPort`,
            url: `${PERF_PHONE_ORIGIN}/`,
            reuseExistingServer: false,
            timeout: 240_000,
          },
        ]
      : []),
    {
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
    ...(PARITY
      ? [
          {
            command: `pnpm exec vite --host 127.0.0.1 --port ${PARITY_PORT} --strictPort`,
            url: `${PARITY_ORIGIN}/@vite/client`,
            reuseExistingServer: false,
            timeout: 30_000,
          },
        ]
      : []),
    ...(LIVE
      ? [
          {
            command: `node e2e/support/fakeCardsApi.mjs ${LIVE_API_PORT}`,
            url: `${LIVE_API}/healthz`,
            reuseExistingServer: false,
            timeout: 30_000,
          },
          {
            command: `pnpm exec vite --host 127.0.0.1 --port ${LIVE_PORT} --strictPort`,
            env: { VITE_TILO_API_URL: LIVE_API },
            url: `${LIVE_ORIGIN}/@vite/client`,
            reuseExistingServer: false,
            timeout: 30_000,
          },
        ]
      : []),
    ...(CP2
      ? [
          {
            command: "uv run --package tilo-api python -m tilo_api",
            cwd: "../..",
            env: { TILO_API_DEV_ORIGINS: CP2_ORIGIN },
            url: `${CP2_API}/healthz`,
            reuseExistingServer: !process.env.CI,
            timeout: 120_000,
          },
          {
            command: `pnpm exec vite --host 127.0.0.1 --port ${CP2_PORT} --strictPort`,
            env: { VITE_TILO_API_URL: CP2_API },
            url: `${CP2_ORIGIN}/@vite/client`,
            reuseExistingServer: false,
            timeout: 30_000,
          },
        ]
      : []),
  ],
});
