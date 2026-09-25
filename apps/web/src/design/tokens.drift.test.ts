import fs from "node:fs";
import { expect, test } from "vitest";
import { CSS_PATH, TS_PATH, generate } from "../../scripts/generate-tokens.mjs";

test("PRD-18.2 tokens: committed tokens.css and tokens.ts match the generator (run `just tokens`)", () => {
  const { css, ts } = generate();
  expect(fs.readFileSync(CSS_PATH, "utf-8")).toBe(css);
  expect(fs.readFileSync(TS_PATH, "utf-8")).toBe(ts);
});
