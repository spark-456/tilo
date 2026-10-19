// FR-ACC-01 (BQ-DSN-04): the level -> tier ceiling and "a skill level can only restrict", as pure view functions.
import { describe, expect, it } from "vitest";
import { LEVEL_LABEL, ceilingOf, effectiveLevel } from "./view";

describe("FR-ACC-01 access levels", () => {
  it("FR-ACC-01 each level names its tier ceiling and Act stays inside the policy engine", () => {
    expect(ceilingOf(0)).toMatch(/blocks every call/i);
    expect(ceilingOf(1)).toMatch(/T0/);
    expect(ceilingOf(2)).toMatch(/T1/);
    expect(ceilingOf(3)).toMatch(/policy/i);
    expect(ceilingOf(3)).toMatch(/T3.*approval card/i);
    expect(LEVEL_LABEL[0]).toBe("Off");
  });

  it("FR-ACC-01 a skill level can only restrict the team level", () => {
    for (let t = 0; t <= 3; t++) {
      expect(effectiveLevel(t, undefined)).toBe(t);
      for (let s = 0; s <= 3; s++) expect(effectiveLevel(t, s)).toBe(Math.min(t, s));
    }
  });
});
