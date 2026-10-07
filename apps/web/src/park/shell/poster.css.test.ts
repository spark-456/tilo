// NFR-01 (PRD 17.1), ticket NFR-01-LANDING: the poster that stands in for the city until it is drawn lives in
// park.shell.css and is a fixed box with no motion and no picture to fetch: it fills the backdrop layer exactly
// (so the city replacing it shifts nothing), it never takes a click, and it paints from tokens, not from a
// new colour (README: no invented colours). The cheaper-path rules for narrow or weak devices, if any, are not
// pinned here.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";

const css = (): string => fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");
const poster = () =>
  parseRules(css()).rules.filter((r) => r.selector.includes(".park-shell__poster"));

describe("NFR_01_LANDING_css: the city poster", () => {
  it("NFR_01_LANDING_css_the_poster_fills_the_backdrop_layer_and_takes_no_click", () => {
    const rules = poster();
    expect(rules.length).toBeGreaterThan(0);
    const decl = (name: string) => rules.map((r) => r.decls.get(name)).find((v) => v !== undefined);
    expect(decl("position")).toBe("absolute");
    expect(decl("inset")).toBe("0");
    expect(decl("pointer-events")).toBe("none");
  });

  it("NFR_01_LANDING_css_the_poster_has_no_motion_no_url_and_no_literal_colour", () => {
    const text = poster()
      .map((r) => [...r.decls.entries()].map(([k, v]) => `${k}: ${v}`).join(";"))
      .join(";");
    expect(text).not.toMatch(/animation|transition|url\(|@keyframes/i);
    expect(text).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });
});
