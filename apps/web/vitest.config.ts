import { defineConfig } from "vitest/config";

// Unit tests only (apps/web/src/**/*.test.ts, apps/web/test-support). End-to-end
// / layout / renderer / accessibility acceptance tests live under apps/web/e2e
// and run with Playwright (see playwright.config.ts), not Vitest.
//
// Two projects. The *typecheck.test.ts files build a TypeScript program synchronously (ts.createProgram, ~10 s
// alone, up to ~80 s when a dozen run in parallel workers on 16 cores). That blocks the worker's event loop past
// vitest's 60 s worker RPC timeout, so a run ended "Timeout calling onTaskUpdate" (exit 1) with every test green,
// and starved the DOM tests next to them (the 5 s timeout of Profile.styles). They now run together in one
// non-isolated fork: one process, one file at a time, with the program shared (test-support/park/typecheck.ts).
const TYPECHECK = ["src/**/typecheck.test.ts", "src/**/*.typecheck.test.ts"];

export default defineConfig({
  // vite-node leaves "%20" in file:// import ids, and this repo's path has spaces.
  resolve: { alias: [{ find: /%20/g, replacement: " " }] },
  test: {
    environment: "node",
    // SEC-10: the Firebase web config the build supplies in production (`just deploy-web`). Fake test values, so
    // the App Check tests reach the SDK (which they replace by a fake); no key literal is committed.
    env: { VITE_FIREBASE_API_KEY: "test-web-api-key", VITE_FIREBASE_PROJECT_ID: "demo-tilo-web" },
    // A jsdom render is a few hundred ms alone but seconds under load; a timeout only has to catch a hang.
    testTimeout: 30_000,
    maxWorkers: 8,
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
          exclude: ["e2e/**", "node_modules/**", ...TYPECHECK],
        },
      },
      {
        extends: true,
        test: {
          name: "typecheck",
          include: TYPECHECK,
          exclude: ["e2e/**", "node_modules/**"],
          pool: "forks",
          poolOptions: { forks: { singleFork: true } },
          isolate: false,
          testTimeout: 180_000,
        },
      },
    ],
  },
});
