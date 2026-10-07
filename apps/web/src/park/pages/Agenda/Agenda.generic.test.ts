// WEB-9c: "No scenario-specific code" (root CLAUDE.md hard rule). The Agenda's logic holds no scenario
// literal: designed values (world, labels, dates, times, amounts, event ids) come from the fixture/Api.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIR = __dirname;
const src = readdirSync(DIR)
  .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
  .map((f) => ({ f, t: readFileSync(join(DIR, f), "utf8") }));

const FORBIDDEN: [string, RegExp][] = [
  ["world id k1", /\bk1\b/i],
  ["supplier name", /Laptop Depot/i],
  ["product name", /scooter/i],
  ["company name", /Meridian|Northwind/i],
  ["person", /Alex Morgan|alex@northwind/i],
  ["amount", /3,?420/],
  ["fixed date", /\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2}\b/],
  ["month literal", /\bSep(?:tember)?\b/],
  ["fixed time", /\b\d{1,2}:\d{2}\b/],
  ["event id compared as a literal", /\.id\s*===?\s*["'`]\w+["'`]/],
  ["id compared as a literal", /===?\s*["'`](?:gate|sync|su|t0|tg)["'`]/],
  ["event id set as a literal", /set(?:Sel|Selected)\(["'`]\w+["'`]\)/],
  ["pin kind compared as a literal", /\bkind\s*===?\s*["'`]\w+["'`]/],
];

describe("WEB_9c_agenda_generic", () => {
  it("WEB_9c_agenda_logic_holds_no_scenario_literal", () => {
    expect(src.length).toBeGreaterThan(5);
    for (const { f, t } of src) {
      const code = t.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
      for (const [what, re] of FORBIDDEN) expect(code, `${f}: ${what}`).not.toMatch(re);
    }
  });
});
