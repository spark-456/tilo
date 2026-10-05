// `just e2e-cp2`: runs the @cp2 Playwright project (apps/web/e2e/cp2) against the real dev API.
// playwright.config.ts starts `tilo-api` (dev mode: fake Director and runner, in-memory store, no
// credentials) and a Vite server with VITE_TILO_API_URL set when TILO_CP2=1. Dev mode makes no paid
// call and refuses live mode itself; this refuses first. Extra arguments go to Playwright. The web
// port is `TILO_CP2_PORT` (default 5391); the API's own port is fixed at 8080 by its Host check
// (services/api dev.py), so two runs at once still collide on it.
import { spawnSync } from "node:child_process";

// Any value that is not plainly "off" counts as live mode ("1", "true", "yes", "on", anything else).
const live = process.env.LIVE?.trim().toLowerCase();
if (live !== undefined && !["", "0", "false", "no", "off"].includes(live)) {
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
