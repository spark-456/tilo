// RUN-INDICATOR css: the run bar's rules in park.shell.css, read as text. Pinned here: it floats at the bottom
// (fixed, safe-area aware), is only as big as its pill (so it blocks no click outside itself), never sits over
// the nav, shifts no layout, and adds no animation or transition of its own (the moving ring is the loader's
// existing `park-shell__ring` class; the honesty allowlists and their tests are untouched).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";
import { stripComments } from "../../../test-support/park/css";

const css = fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");
const rules = parseRules(css).rules.filter((r) => /park-shell__runbar/.test(r.selector));
const bar = rules.find((r) => /^\[data-park\] \.park-shell__runbar$/.test(r.selector));

describe("RUN_INDICATOR css: where the bar sits", () => {
  it("RUN_INDICATOR_css_the_bar_has_a_rule_and_it_is_fixed_at_the_bottom_and_safe_area_aware", () => {
    expect(bar, "no [data-park] .park-shell__runbar rule").toBeDefined();
    expect(bar?.decls.get("position")).toBe("fixed");
    expect(bar?.decls.get("bottom")).toMatch(/env\(safe-area-inset-bottom/);
    expect(bar?.decls.get("top")).toBeUndefined();
  });

  it("RUN_INDICATOR_css_the_bar_is_pill_sized_so_it_blocks_no_click_outside_itself", () => {
    expect(bar?.decls.get("inset")).toBeUndefined();
    expect(bar?.decls.get("width")).toBeUndefined();
    expect(bar?.decls.get("left")).toBe("50%");
    expect(bar?.decls.get("transform")).toBe("translateX(-50%)");
    expect(bar?.decls.get("max-width")).toMatch(/calc\(100vw - \d+px\)/); // fits 390 px wide with a gutter
  });

  it("RUN_INDICATOR_css_the_bar_sits_above_the_page_and_below_the_nav_and_the_popovers", () => {
    const z = Number(bar?.decls.get("z-index"));
    expect(z).toBeGreaterThan(1); // the page column is 1
    expect(z).toBeLessThan(30); // the nav is 30
  });

  it("RUN_INDICATOR_css_the_pill_is_at_least_24px_tall_and_clips_a_long_detail_instead_of_wrapping", () => {
    expect(Number.parseInt(bar?.decls.get("min-height") ?? "0", 10)).toBeGreaterThanOrEqual(24);
    const detail = rules.find((r) => /__runbar-detail$/.test(r.selector));
    expect(detail?.decls.get("text-overflow")).toBe("ellipsis");
    expect(detail?.decls.get("white-space")).toBe("nowrap");
    expect(detail?.decls.get("overflow")).toBe("hidden");
  });
});

describe("RUN_INDICATOR css: no motion of its own", () => {
  it("RUN_INDICATOR_css_no_runbar_rule_has_animation_or_transition", () => {
    expect(rules.length).toBeGreaterThan(0);
    for (const r of rules) {
      for (const [k] of r.decls) expect(k, r.selector).not.toMatch(/^(animation|transition)/);
    }
  });

  it("RUN_INDICATOR_css_no_new_keyframes_the_ring_is_the_loaders_existing_tiloSpin", () => {
    const names = [...stripComments(css).matchAll(/@keyframes\s+([\w-]+)/g)].map((m) => m[1]);
    expect(names.sort()).toEqual([
      "mvXY",
      "tiloFade",
      "tiloSlide",
      "tiloSpin",
      "waddle",
      "walkFrame",
    ]);
  });

  it("RUN_INDICATOR_css_the_bar_uses_tokens_for_colour", () => {
    const decl = (r: typeof bar) => [...(r?.decls.values() ?? [])].join(" ");
    expect(decl(bar)).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});
