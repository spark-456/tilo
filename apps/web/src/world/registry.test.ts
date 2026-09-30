/**
 * P0-08b-player: HR-5 / FR-WLD-04 unit tests for apps/web/src/world/registry.ts.
 *
 * Interface under test (this module does not exist yet, so every import below fails on
 * "Cannot find module" until the builder adds it):
 *
 *   export function isKnownType(type: string): boolean
 *
 * `isKnownType` answers whether `type` (a TiloEvent's `family.verb`, PRD 9.3) is one the
 * harness may emit per contracts/events/registry.yaml (EV-01) — i.e. whether the world/HUD/
 * Story lenses may animate it. HR-5: "Unknown event types appear in the Trace only." The
 * ground truth here is read directly from contracts/events/registry.yaml (root CLAUDE.md:
 * "contracts/ ... win over prose"), not from any generated package, so this test does not
 * depend on packages/contracts-ts being wired into @tilo/web yet.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "vitest";
import { isKnownType } from "./registry";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const REGISTRY_PATH = path.join(REPO_ROOT, "contracts", "events", "registry.yaml");

/** Every `  <family.verb>:` key nested directly under the `types:` mapping. Avoids adding a
 * YAML parser as a dependency for one flat, well-known-shaped file. */
function registeredTypes(): string[] {
  const text = fs.readFileSync(REGISTRY_PATH, "utf-8");
  const lines = text.split("\n");
  const startIndex = lines.findIndex((l) => l.trim() === "types:");
  expect(
    startIndex,
    "contracts/events/registry.yaml has no top-level `types:` key",
  ).toBeGreaterThanOrEqual(0);
  const types: string[] = [];
  for (const line of lines.slice(startIndex + 1)) {
    const m = line.match(/^ {2}([a-z][a-z_]*\.[a-z_]+):\s*$/);
    if (m?.[1]) types.push(m[1]);
    else if (line.length > 0 && !line.startsWith(" ")) break; // left the `types:` block
  }
  return types;
}

test("HR-5 registry: every type registered in contracts/events/registry.yaml is known", () => {
  const types = registeredTypes();
  expect(types.length).toBeGreaterThan(30); // sanity: the registry really has many types
  for (const type of types) {
    expect(isKnownType(type), `isKnownType("${type}") should be true`).toBe(true);
  }
});

test("HR-5 registry: BQ-07's four unregistered types (world.created, user.joined, user.commented, alert.batched) are unknown", () => {
  for (const type of ["world.created", "user.joined", "user.commented", "alert.batched"]) {
    expect(isKnownType(type), `isKnownType("${type}") should be false`).toBe(false);
  }
});

test("HR-5 registry: a well-formed but never-registered type is unknown", () => {
  expect(isKnownType("teleport.vanished")).toBe(false);
});
