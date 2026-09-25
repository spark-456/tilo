/**
 * Drift test for the P0-08a token pipeline (like the generated-types drift
 * check the contracts packages will have): the committed
 * apps/web/src/styles/tokens.css and apps/web/src/design/tokens.ts must equal
 * what the generator produces from the current design/tokens.json right now.
 * If this fails, design/tokens.json changed since the last `just tokens`.
 */
import fs from "node:fs";
import { expect, test } from "vitest";
import { CSS_PATH, TS_PATH, generate } from "../../scripts/generate-tokens.mjs";

test("PRD-18.2 tokens: generated CSS/TS files are not stale (run `just tokens` to regenerate)", () => {
  const { css, ts } = generate();
  expect(fs.readFileSync(CSS_PATH, "utf-8"), "apps/web/src/styles/tokens.css is stale").toBe(css);
  expect(fs.readFileSync(TS_PATH, "utf-8"), "apps/web/src/design/tokens.ts is stale").toBe(ts);
});
