// WEB-1a test support: loads the user's Park City prototype data (design_handoff_tilo_web_app/design/
// tilo-app.js) in a Node vm with a stub `window`, so the typed fixtures can be compared with it.
// Lives outside src/ on purpose: the honesty scan (FR-WLD-09) and the park static checks walk src/.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(here, "..", "..", "..", "..");
export const HANDOFF_DIR = path.join(REPO_ROOT, "design_handoff_tilo_web_app");
export const PROTOTYPE_PATH = path.join(HANDOFF_DIR, "design", "tilo-app.js");
export const HANDOFF_TOKENS_PATH = path.join(HANDOFF_DIR, "tokens.css");
export const HANDOFF_README_PATH = path.join(HANDOFF_DIR, "README.md");
export const PARK_DIR = path.resolve(here, "..", "..", "src", "park");

/** The prototype's `window.TiloApp.data` (D). Loosely typed on purpose: it is the reference side. */
export interface PrototypeData {
  gbp(v: number): string;
  LEVELS: unknown;
  user: unknown;
  today: unknown;
  decisions: unknown[];
  needsLeft(dec?: Record<string, boolean>): number;
  plans(dec?: Record<string, boolean>): unknown;
  worlds(dec?: Record<string, boolean>, added?: unknown[]): unknown[];
  TIERS: Record<string, unknown>;
  makeWorld(mode: string, q: string, i: number): unknown;
  skills: unknown[];
  learn: unknown;
  ledger: unknown;
  agenda: unknown;
  team: unknown;
  connectors: unknown[];
  notifications: unknown[];
}

let cached: PrototypeData | undefined;

export function loadPrototypeData(): PrototypeData {
  if (cached) return cached;
  if (!fs.existsSync(PROTOTYPE_PATH)) {
    throw new Error(
      `WEB-1a parity needs the design handoff prototype at ${PROTOTYPE_PATH}. It is missing: merge the design handoff commit into this branch (design_handoff_tilo_web_app/design/tilo-app.js).`,
    );
  }
  const code = fs.readFileSync(PROTOTYPE_PATH, "utf8");
  const win: { TiloApp?: { data: PrototypeData } } = {};
  vm.runInNewContext(code, { window: win }, { filename: "tilo-app.js" });
  if (!win.TiloApp?.data) {
    throw new Error("tilo-app.js ran but did not set window.TiloApp.data");
  }
  cached = win.TiloApp.data;
  return cached;
}

/** What the fixtures are compared as: JSON-normalised (functions and undefined dropped). */
export function norm<T>(v: T): unknown {
  return JSON.parse(JSON.stringify(v));
}
