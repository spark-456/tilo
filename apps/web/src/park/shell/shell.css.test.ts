// WEB-3b: the one stylesheet of the shell, apps/web/src/park/shell/park.shell.css (plan section 10: one
// stylesheet per area, every selector under [data-park]; plan 8d: the shell ships with a STATIC city, so no
// transition, animation or keyframes; the motion restore is BQ-WEB-3 and brings its own honesty-scan entry).
// The sizes, radii and colours are not read from the file: they are measured on the running page against the
// reference in e2e/park-shell-visual.spec.ts.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";
import { stripComments } from "../../../test-support/park/css";

const css = (): string => fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");

describe("WEB_3b_css: park.shell.css", () => {
  it("WEB_3b_css_every_selector_sits_under_data_park", () => {
    const rules = parseRules(css()).rules;
    expect(rules.length).toBeGreaterThan(10);
    expect(rules.map((r) => r.selector).filter((s) => !s.startsWith("[data-park]"))).toEqual([]);
  });

  it("WEB_3b_css_has_no_transition_animation_or_keyframes", () => {
    expect(stripComments(css())).not.toMatch(
      /\btransition\b|\banimation\b|@keyframes|animation-play-state/i,
    );
    expect(parseRules(css()).others.map((o) => o.head)).toEqual([]);
  });

  it("WEB_3b_css_glass_blur_is_limited_to_the_nav", () => {
    // README Performance: glass blur only on the nav and the Home panels, so inner pages stay solid.
    const blurs = parseRules(css()).rules.filter((r) => r.decls.has("backdrop-filter"));
    expect(blurs.length).toBeLessThanOrEqual(1);
  });
});
