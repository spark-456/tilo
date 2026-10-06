// WEB-MOTION-1 (PRD 9.4 HR-1 to HR-7; docs/open-questions.md BQ-WEB-3, decided by the user 6 Oct 2026;
// ADR-0003a 5): the Park city's ambient motion (cars and walkers) is allowed, and nothing that depicts Tilo's
// own agents is. "Ambient non-agent motion built as designed, on by default, one flag PARK_AMBIENT_MOTION;
// agents animate only from events; narrow reasoned honestyScan.ts allowlist entry".
// This pins the allowlist's SHAPE: where the exceptions may live and what they must say. It does not name a
// file the builder must use; any file under park/shell or park/engines will do.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../test-support/honestyScan";

const SRC = join(__dirname, "..");
const PARK = join(SRC, "park");
const SCAN_TIMEOUT_MS = 30_000;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [p] : [];
  });
}
const parkFiles = walk(PARK).map((p) => relative(SRC, p).replaceAll("\\", "/"));
const rel = (f: string) => `src/${f}`;
const parkEntries = ALLOWLIST.filter((a) => a.file.startsWith("src/park/"));
// The city layer: the shell that draws it and the engine that builds its movers.
const CITY = /^src\/park\/(?:shell|engines)\//;
// The parts of the Park app that show or run agents, worlds, decisions and data.
const AGENT_SIDE = /^src\/park\/(?:pages|components|app|api|tokens|dev)\//;

describe("WEB-MOTION-1 honesty: ambient city motion is allowed, agent motion is not", () => {
  it(
    "WEB-MOTION-1 the city's ambient motion is on the allowlist, in the city layer only, each entry with its reason",
    { timeout: SCAN_TIMEOUT_MS },
    () => {
      expect(parkEntries.length, "no Park entry: the city cannot move yet").toBeGreaterThan(0);
      for (const a of parkEntries) {
        expect(a.file, `${a.file} is not the city layer`).toMatch(CITY);
        expect(a.reason.length).toBeGreaterThanOrEqual(30);
        expect(
          a.reason,
          `${a.file}: the reason says the motion is ambient scenery, not an agent`,
        ).toMatch(/ambient|non-agent|scenery/i);
        expect(
          a.reason,
          `${a.file}: the reason says agents animate only from recorded events`,
        ).toMatch(/event/i);
      }
    },
  );

  it("WEB-MOTION-1 every Park entry is used (none is stale) and none is a timer, a ticker or a tween library", () => {
    for (const a of parkEntries) {
      const used = scanSource(a.file, readFileSync(join(SRC, "..", a.file), "utf8")).some(
        (v) => v.rule === a.rule,
      );
      expect(used, `${a.file} no longer uses ${a.rule}: remove the entry`).toBe(true);
      // HR-2: a repeating timer, a Pixi ticker or a tween library is how an idle "working" animation is built.
      expect(["interval", "pixi-ticker", "tween-library"]).not.toContain(a.rule);
    }
  });

  it("WEB-MOTION-1 the world and stage entries are exactly the two the choreographer era had", () => {
    const rest = ALLOWLIST.filter((a) => !a.file.startsWith("src/park/")).map(
      (a) => `${a.file}|${a.rule}`,
    );
    expect(rest.sort()).toEqual(["src/stage/Stage.tsx|raf", "src/world/runWorld.ts|raf"]);
  });

  it(
    "WEB-MOTION-1 nothing that shows agents, worlds, decisions or data in the Park app animates at all",
    { timeout: SCAN_TIMEOUT_MS },
    () => {
      const hits = parkFiles
        .filter((f) => AGENT_SIDE.test(rel(f)))
        .flatMap((f) => scanSource(rel(f), readFileSync(join(SRC, f), "utf8")))
        .map((v) => `${v.file}:${v.line} ${v.rule}`);
      expect(hits, "agent motion comes only from recorded events, never from page code").toEqual(
        [],
      );
      expect(ALLOWLIST.some((a) => AGENT_SIDE.test(a.file))).toBe(false);
    },
  );

  it("WEB-MOTION-1 the allowlist stays narrow: at most one entry per rule per Park file, and no entry outside the city layer", () => {
    const seen = new Set<string>();
    for (const a of parkEntries) {
      const key = `${a.file}|${a.rule}`;
      expect(seen.has(key), `${key} is listed twice`).toBe(false);
      seen.add(key);
      expect(a.file).toMatch(CITY);
    }
  });

  it("WEB-MOTION-1 one flag, PARK_AMBIENT_MOTION, gates the city motion: exactly one source file reads it", () => {
    const readers = parkFiles.filter((f) =>
      /PARK_AMBIENT_MOTION/.test(readFileSync(join(SRC, f), "utf8")),
    );
    expect(readers.length, "BQ-WEB-3: one flag, default on").toBe(1);
    expect(readers[0]).toMatch(/^park\/(?:shell|app|engines)\//);
  });
});
