// WEB-7: "No scenario-specific code" (root CLAUDE.md hard rule). The Ledger's logic and styles hold no
// scenario literal: the world to open and the words of a decision come from `Decision` and
// `Decision.facts` (fixtures/additive.ts) through the Api, never from the page.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIR = __dirname;
const src = readdirSync(DIR)
  .filter((f) => /\.(tsx?|css)$/.test(f) && !/\.test\.tsx?$/.test(f))
  .map((f) => ({ f, t: readFileSync(join(DIR, f), "utf8") }));

const FORBIDDEN: [string, RegExp][] = [
  ["world id k1", /\bk1\b/i],
  ["supplier name", /Laptop Depot/i],
  ["product name", /scooter/i],
  ["company name", /Meridian|Northwind/i],
  ["person", /Alex Morgan|alex@northwind/i],
  ["amount", /3,?420/],
  ["goods", /battery|suppliers?\b/i],
  ["agent role", /Builder agent/i],
  ["button label", /Send brief/i],
  ["wait time", /\d+ h \d+ min/],
];

describe("WEB_7_ledger_generic", () => {
  it("WEB_7_ledger_logic_holds_no_scenario_literal", () => {
    expect(src.length).toBeGreaterThan(8);
    // Comments are the author's notes, not rendered text: only code and strings are checked.
    for (const { f, t } of src) {
      const code = t.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
      for (const [what, re] of FORBIDDEN) expect(code, `${f}: ${what}`).not.toMatch(re);
    }
  });
});
