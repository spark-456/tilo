// FR-ACC-02: the picker's allowed levels come from the same rule as the engine (tilo_policy.access_levels
// effective_level = min(team, skill)). The shared fixture is also asserted by the Python test.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { LEVEL_LABEL } from "../Connectors/view";
import { LEVELS, allowedLevels, shownLevel } from "./skillAccess";

const url = new URL(
  "../../../../../../packages/policy/tests/fixtures/effective_level_pairs.json",
  import.meta.url,
);
const fx = JSON.parse(readFileSync(url, "utf8")) as {
  levels: string[];
  pairs: [number, number, number][];
};

describe("FR-ACC-02 skill tool level picker", () => {
  it("FR-ACC-02 the level labels are the engine's four levels in order", () => {
    expect(LEVEL_LABEL.map((l) => l.toLowerCase())).toEqual(fx.levels);
    expect([...LEVELS]).toEqual([...LEVEL_LABEL]);
  });

  it("FR-ACC-02 shownLevel equals the engine's effective level for every pair", () => {
    for (const [team, skill, eff] of fx.pairs) expect(shownLevel(team, skill)).toBe(eff);
  });

  it("FR-ACC-02 a level is offered exactly when the engine would keep it (never above the team level)", () => {
    for (let team = 0; team <= 3; team++) {
      const kept = fx.pairs.filter(([t, s, e]) => t === team && e === s).map(([, s]) => s);
      expect(allowedLevels(team)).toEqual(kept);
      expect(Math.max(...allowedLevels(team))).toBe(team);
    }
  });

  it("FR-ACC-02 a stale or tampered value is used as the team level, never raised", () => {
    for (const bad of [4, 99, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(shownLevel(2, bad)).toBe(2);
    }
    expect(shownLevel(2, undefined)).toBe(2);
    expect(shownLevel(5, 1)).toBeLessThanOrEqual(3); // a bad team level is clamped into the four levels
  });
});
