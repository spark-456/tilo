// `just e2e-cp2`: runs the @cp2 Playwright project (apps/web/e2e/cp2) against the real dev API.
// playwright.config.ts starts `tilo-api` (dev mode: fake Director and runner, in-memory store, no
// credentials) and a Vite server with VITE_TILO_API_URL set when TILO_CP2=1. Dev mode makes no paid
// call and refuses live mode itself; this refuses first. Extra arguments go to Playwright.
import { spawnSync } from "node:child_process";

if (process.env.LIVE === "1") {
  console.error("e2e-cp2 runs on fake providers only: unset LIVE and run it again.");
  process.exit(1);
}

const result = spawnSync(
  "pnpm",
  ["exec", "playwright", "test", "--project=cp2", "--workers=1", ...process.argv.slice(2)],
  {
    cwd: new URL("..", import.meta.url),
    stdio: "inherit",
    shell: process.platform === "win32",
    env: { ...process.env, TILO_CP2: "1" },
  },
);
process.exit(result.status ?? 1);
