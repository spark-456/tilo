/**
 * P0-08a token pipeline acceptance tests (PRD 18.2 "Design system", BQ-10, BQ-11).
 *
 * These test the OUTPUT of the generator described in the ticket ("a
 * cross-platform Node or Python script that reads design/tokens.json and
 * generates apps/web/src/styles/tokens.css and apps/web/src/design/tokens.ts"),
 * not the generator script itself — its location and language are the
 * builder's choice. Until that generator exists and has been run, both
 * generated files are missing and every test below fails on a "file not
 * found" / "module not found" error — the expected failure for this ticket
 * per the test-writer rule (fail now for the right reason).
 *
 * CSS variable naming convention and colour-role enumeration are fixed in
 * ../../test-support/tokenRoles.ts; see that file for the ambiguity note.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { expect, test } from "vitest";
import {
  knownBrandHexValues,
  missingColorRoles,
  readColorRoles,
  REPO_ROOT,
} from "../../test-support/tokenRoles";

const TOKENS_CSS_PATH = path.join(REPO_ROOT, "apps", "web", "src", "styles", "tokens.css");
const TOKENS_TS_PATH = path.join(REPO_ROOT, "apps", "web", "src", "design", "tokens.ts");

function readGeneratedCss(): string {
  return fs.readFileSync(TOKENS_CSS_PATH, "utf-8");
}

async function importGeneratedTokens(): Promise<Record<string, unknown>> {
  const mod = (await import(pathToFileURL(TOKENS_TS_PATH).href)) as {
    tokens?: Record<string, unknown>;
    default?: Record<string, unknown>;
  };
  const value = mod.tokens ?? mod.default;
  if (!value) {
    throw new Error(
      `${TOKENS_TS_PATH} must export a "tokens" object (named or default export)`,
    );
  }
  return value;
}

function getIn(obj: unknown, dotPath: string): unknown {
  return dotPath
    .split(".")
    .reduce<unknown>(
      (acc, key) => (acc && typeof acc === "object" ? (acc as Record<string, unknown>)[key] : undefined),
      obj,
    );
}

test("PRD-18.2 tokens: every colour role in design/tokens.json becomes a CSS custom property", () => {
  const css = readGeneratedCss();
  const roles = readColorRoles();
  expect(roles.length).toBeGreaterThan(10); // sanity: the fixture actually has roles worth checking
  for (const role of roles) {
    expect(css, `missing ${role.cssVar} for colour role "color.${role.path}"`).toContain(
      `${role.cssVar}:`,
    );
  }
});

test("PRD-18.2 tokens: every colour role in design/tokens.json becomes a TS module entry", async () => {
  const tokens = await importGeneratedTokens();
  const roles = readColorRoles();
  for (const role of roles) {
    const dotPath = `color.${role.path}`;
    const value = getIn(tokens, dotPath);
    expect(value, `tokens.${dotPath} is missing from the generated TS module`).toBeDefined();
  }
});

test("BQ-11 tokens: signal.gate, policy and ink.3 (null in design/tokens.json) are exactly the missing roles", () => {
  const missingPaths = missingColorRoles()
    .map((r) => r.path)
    .sort();
  expect(missingPaths).toEqual(["ink.3", "policy", "signal.gate"]);
});

test("BQ-11 tokens: missing roles get a neutral grey fallback, never an invented brand colour", async () => {
  const tokens = await importGeneratedTokens();
  const brandHexes = new Set(knownBrandHexValues().map((h) => h.toLowerCase()));

  for (const role of missingColorRoles()) {
    const value = getIn(tokens, `color.${role.path}`);
    expect(typeof value, `tokens.color.${role.path} should resolve to a colour string`).toBe(
      "string",
    );
    const hex = (value as string).toLowerCase();
    expect(hex, `${role.path} fallback must be a hex colour`).toMatch(/^#[0-9a-f]{6}$/);

    const r = hex.slice(1, 3);
    const g = hex.slice(3, 5);
    const b = hex.slice(5, 7);
    expect(r === g && g === b, `${role.path} fallback ${hex} is not a neutral grey`).toBe(true);
    expect(
      brandHexes.has(hex),
      `${role.path} fallback ${hex} must not reuse or invent a brand/signal colour`,
    ).toBe(false);
  }
});

test("BQ-11 tokens: the generated CSS marks each missing role with a 'missing in design exports' comment", () => {
  const css = readGeneratedCss();
  const occurrences = (css.match(/missing in design exports/g) ?? []).length;
  expect(occurrences).toBeGreaterThanOrEqual(missingColorRoles().length);
});

test(
  "BQ-10 tokens: PRD 18.2 values win over the design-export values for control radius, " +
    "card radius, button height and camera duration",
  async () => {
    const tokens = await importGeneratedTokens();
    const css = readGeneratedCss();

    // PRD 18.2 "Shape": 12 px controls, 20 px cards (exports say 16 / 24 — BQ-10).
    expect(getIn(tokens, "radius.controls")).toBe(12);
    expect(getIn(tokens, "radius.cards")).toBe(20);
    expect(css).toContain("--radius-controls: 12px");
    expect(css).toContain("--radius-cards: 20px");

    // PRD 18.2 "Pressable button": 48 px desktop, 52 px mobile (exports say 56 on mobile — BQ-10).
    expect(getIn(tokens, "button.height.desktop")).toBe(48);
    expect(getIn(tokens, "button.height.mobile")).toBe(52);
    expect(css).toContain("--button-height-desktop: 48px");
    expect(css).toContain("--button-height-mobile: 52px");

    // PRD 18.2 "Motion": 320 ms camera (exports say 650 ms — BQ-10).
    expect(getIn(tokens, "motion.cameraMs")).toBe(320);
    expect(css).toContain("--motion-camera-ms: 320ms");
  },
);
