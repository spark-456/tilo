/**
 * P0-08a fonts acceptance test (ticket item 2: "Fonts: Nunito, Nunito Sans and
 * JetBrains Mono (OFL-1.1) self-hosted via @fontsource packages; record
 * licences in docs/licences.md.", CLAUDE.md "record every dependency's
 * licence").
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "vitest";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const LICENCES_PATH = path.join(REPO_ROOT, "docs", "licences.md");

test("PRD-18.2 fonts: Nunito, Nunito Sans and JetBrains Mono are recorded in docs/licences.md under OFL-1.1", () => {
  const text = fs.readFileSync(LICENCES_PATH, "utf-8");
  for (const font of ["Nunito Sans", "Nunito", "JetBrains Mono"]) {
    expect(text.includes(font), `${font} is not listed in docs/licences.md`).toBe(true);
  }
  expect(text, "docs/licences.md must record the fonts' OFL-1.1 licence").toMatch(/OFL-1\.1/);
});
