// WEB-4 style spec: Home.css is parsed and checked against the numbers of the reference page
// (design_handoff_tilo_web_app/design/Tilo App Home.dc.html, inline styles, measured as computed values at
// 1440 x 900 and listed in e2e/park-home.spec.ts). Each row below is one declaration the reference makes;
// the stylesheet may spread them over rules as it likes (the real cascade is checked in the browser by the
// e2e spec). Conventions of the Park pages (plan section 10): every selector under [data-park] and tied to
// the page by a `park-home-` class, colours as var(--token) except the three the README hard-codes
// (#F0A500, #1F1D2B, #FFFFFF), no transition / animation / @keyframes (BQ-WEB-3), night comes from the tokens.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { type CssRule, norm, parseRules } from "../../../../test-support/park/componentsCss";
import { stripComments } from "../../../../test-support/park/css";

const CSS_PATH = join(__dirname, "Home.css");
const css = () => readFileSync(CSS_PATH, "utf8");
const parsed = () => parseRules(css());

const has = (rules: readonly CssRule[], prop: string, value: string): boolean => {
  const want = norm(value);
  const props = prop === "background" ? ["background", "background-color"] : [prop];
  return rules.some((r) => props.some((p) => r.decls.has(p) && norm(r.decls.get(p)) === want));
};

// [what it styles, property, value] from design/studio-v2 "Tilo S Home" (UI-STUDIO-2), as role tokens.
const ROWS: readonly [string, string, string][] = [
  // the page column
  ["page width", "max-width", "1296px"],
  // POLISH-1: the side gutter is the shell's --park-page-pad (8px), so Home, Worlds and Team share a left edge.
  ["page padding", "padding", "120px 8px 64px"],
  ["page gap", "gap", "36px"],
  // greeting type
  ["date line size", "font-size", "13px"],
  ["date line ink", "color", "var(--ink3)"],
  ["h1 size", "font-size", "52px"],
  ["h1 weight", "font-weight", "700"],
  ["h1 tracking", "letter-spacing", "-2px"],
  ["h1 line height", "line-height", "1.05"],
  ["summary size", "font-size", "18px"],
  ["summary ink", "color", "var(--ink2)"],
  // the ask box
  ["ask box fill", "background", "var(--card)"],
  ["ask box border", "border", "1px solid var(--line)"],
  ["ask box radius", "border-radius", "24px"],
  ["ask box padding", "padding", "24px"],
  ["ask box shadow", "box-shadow", "var(--sh)"],
  ["helper tile size", "width", "52px"],
  ["helper tile radius", "border-radius", "16px"],
  ["switch track fill", "background", "var(--sunk)"],
  ["switch item radius", "border-radius", "10px"],
  ["go height", "height", "52px"],
  ["go radius", "border-radius", "16px"],
  ["go size", "font-size", "17px"],
  ["go fill", "background", "var(--priFill, var(--heroFill))"],
  ["go lip", "box-shadow", "0 3px 0 var(--priLip, var(--heroFill))"],
  ["chip height", "min-height", "44px"],
  // Your worlds and the side column
  ["grid columns", "grid-template-columns", "minmax(0, 1fr) 340px"],
  ["section title size", "font-size", "28px"],
  ["section title tracking", "letter-spacing", "-0.8px"],
  ["world cards", "grid-template-columns", "repeat(3, minmax(0, 1fr))"],
  ["world card radius", "border-radius", "20px"],
  ["world picture height", "height", "150px"],
  ["side column offset", "padding-top", "52px"],
  ["side card padding", "padding", "20px"],
  ["spend figure size", "font-size", "32px"],
  // needs pill, review chip, caught up
  ["pill fill", "background", "var(--amberSoft)"],
  ["pill border", "border", "1px solid var(--amberLine)"],
  ["review chip fill", "background", "#F0A500"],
  ["review chip ink", "color", "#1F1D2B"],
  ["caught up fill", "background", "var(--okSoft)"],
  ["caught up disc fill", "background", "var(--ok)"],
];

describe("WEB_4_home_styles: Home.css exists and follows the Park conventions", () => {
  it("WEB_4_home_styles_Home_css_exists_and_HomePage_imports_it", () => {
    expect(existsSync(CSS_PATH), "src/park/pages/Home/Home.css").toBe(true);
    const page = readFileSync(join(__dirname, "HomePage.tsx"), "utf8");
    expect(page).toMatch(/import\s+["']\.\/Home\.css["']/);
  });

  it("WEB_4_home_styles_every_selector_is_under_data_park_and_tied_to_a_park_home_class", () => {
    const { rules } = parsed();
    expect(rules.length).toBeGreaterThan(20);
    for (const r of rules) {
      expect(r.selector, r.selector).toMatch(/^\[data-park\]/);
      expect(r.selector, `${r.selector} must carry a park-home- class`).toMatch(
        /\.park-home-[\w-]+/,
      );
    }
  });

  it("WEB_4_home_styles_no_transition_animation_keyframes_or_will_change", () => {
    const text = stripComments(css());
    expect(text).not.toMatch(/\btransition\b|\banimation\b|@keyframes|will-change/i);
    expect(parsed().others.map((o) => o.head)).toEqual([]);
  });

  it("WEB_4_home_styles_colours_are_tokens_except_the_ones_the_README_hard_codes", () => {
    const text = stripComments(css());
    const hex = [...text.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0].toUpperCase());
    // #F0A500 with #1F1D2B (needs), #FFFFFF (on hero) and the #5A3FE0 focus ring (README "Interactions").
    for (const h of hex)
      expect(["#F0A500", "#1F1D2B", "#FFFFFF", "#5A3FE0"], `hard-coded ${h}`).toContain(h);
    const rgb = [...text.matchAll(/rgba?\([^)]*\)/g)].map((m) => norm(m[0]));
    expect(rgb.filter((c) => c !== "rgba(31,29,43,.16)")).toEqual([]);
  });

  it("WEB_4_home_styles_night_comes_from_the_tokens_not_from_overrides_here", () => {
    expect(stripComments(css())).not.toMatch(/data-time/);
  });
});

describe("STUDIO_2_home_styles: the Studio card and type (no glass)", () => {
  it("STUDIO_2_home_styles_one_rule_holds_the_whole_card_recipe_and_no_glass_blur", () => {
    const card = parsed().rules.filter(
      (r) =>
        norm(r.decls.get("background") ?? r.decls.get("background-color")) ===
          norm("var(--card)") &&
        norm(r.decls.get("border")) === norm("1px solid var(--line)") &&
        norm(r.decls.get("box-shadow")) === norm("var(--sh)"),
    );
    expect(card.length, "a rule with fill, hairline and shadow").toBeGreaterThanOrEqual(1);
    expect(stripComments(css())).not.toMatch(/backdrop-filter/);
  });

  it("STUDIO_2_home_styles_the_h1_rule_is_52px_700", () => {
    const h1 = parsed().rules.filter(
      (r) =>
        norm(r.decls.get("font-size")) === "52px" && norm(r.decls.get("font-weight")) === "700",
    );
    expect(h1.length).toBeGreaterThanOrEqual(1);
  });
});

describe("WEB_4_home_styles: every value of the reference's inline styles", () => {
  it.each(ROWS)("WEB_4_home_styles_%s_%s_%s", (what, prop, value) => {
    expect(has(parsed().rules, prop, value), `${what}: ${prop}: ${value}`).toBe(true);
  });

  it("WEB_4_home_styles_hover_rules_for_rows_and_buttons_exist_as_states_not_motion", () => {
    const hover = parsed().rules.filter((r) => /:hover/.test(r.selector));
    expect(has(hover, "background", "var(--rowHover)")).toBe(true);
    expect(has(hover, "filter", "brightness(1.08)")).toBe(true);
  });
});

describe("QA_13OCT_home_phone_layout: one scrolling column, nothing pinned by an offset", () => {
  // UI-STUDIO-2: the page is a flowing column at every width; the phone block starts at 840px (compact nav).
  const block = (media: string): CssRule[] => {
    const blocks =
      css().match(new RegExp(`@media \\(max-width: ${media}\\) \\{[\\s\\S]*?\\n\\}`, "g")) ?? [];
    return blocks.flatMap((b) => parseRules(b).rules);
  };
  const decl = (rules: CssRule[], selector: string, prop: string): string | undefined =>
    rules
      .filter((r) => r.selector === selector)
      .map((r) => norm(r.decls.get(prop)))
      .filter((v) => v !== "")
      .pop();

  it("QA_13OCT_home_phone_root_is_a_flex_column_in_the_flow", () => {
    const root = parsed().rules.filter((r) => r.selector === "[data-park] .park-home-root");
    expect(decl(root, "[data-park] .park-home-root", "display")).toBe("flex");
    expect(decl(root, "[data-park] .park-home-root", "flex-direction")).toBe("column");
    for (const sel of [
      ".park-home-root",
      ".park-home-composer",
      ".park-home-legal",
      ".park-home-today",
    ]) {
      const pos = decl(parsed().rules, `[data-park] ${sel}`, "position");
      expect(pos === undefined || pos === "static" || pos === "relative", sel).toBe(true);
    }
  });

  it("QA_13OCT_home_phone_side_column_and_cards_stack_in_one_column", () => {
    expect(decl(block("1179px"), "[data-park] .park-home-grid", "grid-template-columns")).toBe(
      "minmax(0,1fr)",
    );
    expect(decl(block("840px"), "[data-park] .park-home-cards", "grid-template-columns")).toBe(
      "minmax(0,1fr)",
    );
  });

  it("QA_13OCT_home_phone_the_ask_box_input_stays_readable", () => {
    expect(decl(block("840px"), "[data-park] .park-home-panel .park-home-input", "font-size")).toBe(
      "19px",
    );
    expect(decl(block("840px"), "[data-park] .park-home-hint", "flex")).toBe("1 1 100%");
  });
});
