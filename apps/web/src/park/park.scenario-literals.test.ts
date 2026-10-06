// Root CLAUDE.md "no scenario-specific code": the demo scenario's names, amounts and people are data (the
// fixtures behind the Api), never logic or markup. This scans apps/web/src/park for the scenario's
// literals and fails on any outside the places that are allowed to hold them:
//   - park/api/fixtures/ (the data itself),
//   - test files and test-support (they assert on the data),
//   - park/dev/ (the /dev/components gallery's sample text: a tracked follow-up to make it neutral).
// Pages written later come with their own copy from the Api; they may not hard-code the scenario either.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";

const PARK = __dirname;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.(ts|tsx|css)$/.test(name) ? [p] : [];
  });
}

const allowed = (rel: string): boolean =>
  rel.startsWith(`api${sep}fixtures${sep}`) ||
  rel.startsWith(`dev${sep}`) ||
  /\.test\.tsx?$/.test(rel);

const FILES = walk(PARK)
  .map((p) => ({ path: p, rel: relative(PARK, p) }))
  .filter((f) => !allowed(f.rel));

/** Case-insensitive words and names of the scenario. */
const INSENSITIVE: readonly [string, RegExp][] = [
  ["k1", /\bk1\b/i],
  ["scooter", /scooter/i],
  ["laptop depot", /laptop depot/i],
  ["meridian", /meridian/i],
  ["northwind", /northwind/i],
];
/** Exact strings. */
const EXACT: readonly string[] = ["£3,420", "Alex Morgan", "alex@northwind.co"];

describe("park_scenario_literals: no scenario text in park logic, markup or styles", () => {
  it("park_scenario_literals_the_scan_sees_the_source_tree", () => {
    expect(FILES.length).toBeGreaterThan(40);
    expect(FILES.some((f) => f.rel === `shell${sep}AppShell.tsx`)).toBe(true);
    expect(FILES.some((f) => f.rel.includes("fixtures"))).toBe(false);
  });

  it("park_scenario_literals_none_outside_the_fixtures_tests_and_the_dev_gallery", () => {
    const hits: string[] = [];
    for (const f of FILES) {
      readFileSync(f.path, "utf8")
        .split(/\r?\n/)
        .forEach((line, i) => {
          for (const [name, re] of INSENSITIVE) {
            if (re.test(line)) hits.push(`${f.rel.replaceAll(sep, "/")}:${i + 1} ${name}`);
          }
          for (const s of EXACT) {
            if (line.includes(s)) hits.push(`${f.rel.replaceAll(sep, "/")}:${i + 1} ${s}`);
          }
        });
    }
    expect(hits).toEqual([]);
  });
});
