// Test-only helper for ticket P0-08b-player. Loads the village-basic layout and event
// stream straight from contracts/ (the frozen source of truth) for unit tests under
// apps/web/src/world/*.test.ts, the same REPO_ROOT convention as tokenRoles.ts.
//
// Deliberately untyped as `unknown` / loosely typed here (not `import type { Layout, Event }
// from "@tilo/contracts"`): this file is read at test *runtime* by plain fs+JSON, so it has no
// compile-time dependency on the generated contracts-ts package either.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
export const CONTRACTS_DIR = path.join(REPO_ROOT, "contracts");

export const VILLAGE_BASIC_LAYOUT_PATH = path.join(
  CONTRACTS_DIR,
  "fixtures",
  "layout",
  "valid",
  "village_basic.json",
);
export const VILLAGE_BASIC_STREAM_PATH = path.join(
  CONTRACTS_DIR,
  "fixtures",
  "streams",
  "village-basic.jsonl",
);

/** Parses a `.jsonl` event stream file (one JSON object per line, blank lines ignored). */
export function readJsonl(filePath: string): Record<string, unknown>[] {
  return fs
    .readFileSync(filePath, "utf-8")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

export function readJson(filePath: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

/** The village-basic WorldLayout (contracts/fixtures/layout/valid/village_basic.json). */
export function villageBasicLayout(): Record<string, unknown> {
  return readJson(VILLAGE_BASIC_LAYOUT_PATH);
}

/** The 44 recorded events of the village-basic run, in `seq` order. */
export function villageBasicEvents(): Record<string, unknown>[] {
  return readJsonl(VILLAGE_BASIC_STREAM_PATH);
}
