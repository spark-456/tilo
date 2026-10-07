// WEB-MOTION-2 fix pass, stylesheet and boot file: nothing that is fading out, waiting or not yet in takes a click,
// and a font face that fails to load is not an uncaught rejection on a Park path.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";

const css = fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");
const rules = parseRules(css).rules;
const noClicks = (selector: RegExp): boolean =>
  rules.some((r) => selector.test(r.selector) && r.decls.get("pointer-events") === "none");

describe("WEB-MOTION-2 guards css: a layer on its way out takes no click", () => {
  it("WEB-MOTION-2 guards css: the world card's scrim has pointer-events none while its card is leaving", () => {
    expect(noClicks(/\.park-scrim:has\(>\s*\.park-shell__card--leaving\)/)).toBe(true);
  });

  it("WEB-MOTION-2 guards css: the page outlet has pointer-events none in the out, pre, wait and hold phases", () => {
    for (const phase of ["out", "pre", "wait", "hold"]) {
      expect(
        noClicks(new RegExp(`park-shell__main\\[data-phase="${phase}"\\]`)),
        `phase ${phase}`,
      ).toBe(true);
    }
  });

  it("WEB-MOTION-2 guards css: the fading splash already has pointer-events none", () => {
    expect(noClicks(/park-shell__boot--out/)).toBe(true);
  });
});

describe("WEB-MOTION-2 guards main: font loads are handled on every path", () => {
  it("WEB-MOTION-2 guards main: each document.fonts.load promise has its own catch (a Park path renders without waiting)", () => {
    const main = fs.readFileSync(path.join(__dirname, "..", "..", "main.tsx"), "utf8");
    expect(main).toMatch(/document\.fonts\.load\(f\)\s*\.catch\(/);
    expect(main).toMatch(/isParkPath\(/);
  });
});
