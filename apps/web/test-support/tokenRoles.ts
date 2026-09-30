// Test-only helper for ticket P0-08a (not shipped app code). Reads
// design/tokens.json directly and computes the colour-role -> CSS-variable /
// TS-module-path mapping the token generator is expected to produce.
//
// PRD 18.2 fixes the token *roles* but not the generated variable names, so
// this naming convention is the ambiguity test-writer resolved (logged in the
// P0-08a report and docs/open-questions.md):
//   CSS custom property : `--color-<role-path-with-hyphens>`
//     color.brand.primary -> --color-brand-primary
//     color.signal.gate   -> --color-signal-gate
//     color.ink.3         -> --color-ink-3
//   TS module entry      : `tokens.color.<...path>`, same nesting as the
//     source JSON (e.g. tokens.color.ink["3"]).
//
// `color.unmapped` is excluded: design/tokens.json's own $meta description
// calls those "stray" swatches with no role name, not design-system roles.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
export const TOKENS_JSON_PATH = path.join(REPO_ROOT, "design", "tokens.json");

export interface ColorRole {
  /** Dot path inside `color`, e.g. "brand.primary", "signal.gate", "district.hall". */
  path: string;
  /** The literal value from design/tokens.json — a hex string, or null when missing. */
  value: string | null;
  /** The CSS custom property name this role is expected to become. */
  cssVar: string;
}

function isLeaf(node: unknown): node is { value: unknown } {
  return (
    typeof node === "object" &&
    node !== null &&
    !Array.isArray(node) &&
    Object.prototype.hasOwnProperty.call(node, "value")
  );
}

function readTokensJson(): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(TOKENS_JSON_PATH, "utf-8"));
}

/** Every colour role under `color` in design/tokens.json. */
export function readColorRoles(): ColorRole[] {
  const raw = readTokensJson();
  const roles: ColorRole[] = [];

  function walk(node: unknown, segments: string[]) {
    if (segments[0] === "unmapped") return;
    if (typeof node !== "object" || node === null || Array.isArray(node)) return;
    if (isLeaf(node)) {
      const value = (node as { value: unknown }).value;
      roles.push({
        path: segments.join("."),
        value: value === null ? null : String(value),
        cssVar: `--color-${segments.join("-")}`,
      });
      return;
    }
    for (const [key, child] of Object.entries(node as Record<string, unknown>)) {
      walk(child, [...segments, key]);
    }
  }

  walk((raw.color as Record<string, unknown>) ?? {}, []);
  return roles;
}

/** Colour roles design/tokens.json marks as missing (null value) — BQ-11. */
export function missingColorRoles(): ColorRole[] {
  return readColorRoles().filter((r) => r.value === null);
}

/** Every real, sourced hex value in the colour roles — used to prove a
 * "missing" fallback never reuses or invents a brand/signal colour. */
export function knownBrandHexValues(): string[] {
  return readColorRoles()
    .map((r) => r.value)
    .filter((v): v is string => v !== null && /^#[0-9a-f]{6}$/i.test(v));
}
