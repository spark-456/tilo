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

// [what it styles, property, value] straight from the reference. Values are the reference's own.
const ROWS: readonly [string, string, string][] = [
  // glass: hero (left), Today panel (right), composer panel (bottom)
  ["glass fill", "background", "var(--gBg)"],
  ["glass border", "border", "1px solid var(--gBd)"],
  ["glass blur", "backdrop-filter", "var(--gFx)"],
  ["glass blur (webkit)", "-webkit-backdrop-filter", "var(--gFx)"],
  ["glass shadow", "box-shadow", "var(--sh)"],
  ["hero position", "position", "absolute"],
  ["hero left", "left", "24px"],
  ["hero top", "top", "96px"],
  ["hero width", "width", "500px"],
  ["hero max width", "max-width", "calc(100% - 48px)"],
  ["hero padding", "padding", "24px 26px 22px"],
  ["hero radius", "border-radius", "28px"],
  ["hero gap", "gap", "12px"],
  ["hero layer", "z-index", "3"],
  ["Today panel right", "right", "24px"],
  ["Today panel width", "width", "352px"],
  ["Today panel max height", "max-height", "calc(100% - 330px)"],
  ["Today panel scrolls", "overflow-y", "auto"],
  ["Today panel padding", "padding", "8px"],
  ["Today panel radius", "border-radius", "26px"],
  ["Today panel gap", "gap", "6px"],
  ["composer column bottom", "bottom", "24px"],
  ["composer column width", "width", "1040px"],
  ["composer column layer", "z-index", "4"],
  ["composer column gap", "gap", "12px"],
  ["composer panel padding", "padding", "10px"],
  ["composer panel gap", "gap", "8px"],
  // greeting type
  ["date line size", "font-size", "13px"],
  ["date line tracking", "letter-spacing", "0.7px"],
  ["h1 size", "font-size", "50px"],
  ["h1 weight", "font-weight", "900"],
  ["h1 tracking", "letter-spacing", "-1.4px"],
  ["h1 line height", "line-height", "1"],
  ["summary size", "font-size", "17px"],
  ["summary line height", "line-height", "1.45"],
  // needs pill, review chip, caught up
  ["pill fill", "background", "var(--amberSoft)"],
  ["pill border", "border", "1px solid var(--amberLine)"],
  ["pill padding", "padding", "4px 5px 4px 4px"],
  ["pill size", "font-size", "14.5px"],
  ["pill gap", "gap", "10px"],
  ["pill tile fill", "background", "var(--amberTile)"],
  ["pill tile size", "width", "32px"],
  ["review chip fill", "background", "#F0A500"],
  ["review chip ink", "color", "#1F1D2B"],
  ["review chip height", "height", "30px"],
  ["review chip padding", "padding", "0 14px"],
  ["review chip size", "font-size", "13.5px"],
  ["caught up fill", "background", "var(--okSoft)"],
  ["caught up padding", "padding", "6px 16px 6px 6px"],
  ["caught up disc fill", "background", "var(--ok)"],
  ["caught up disc size", "width", "28px"],
  // Live now
  ["panel title size", "font-size", "15px"],
  ["panel link size", "font-size", "13.5px"],
  ["panel link ink", "color", "var(--heroInk)"],
  ["live row columns", "grid-template-columns", "40px minmax(0, 1fr) auto"],
  ["live row padding", "padding", "7px 10px 7px 7px"],
  ["live row radius", "border-radius", "16px"],
  ["live tile radius", "border-radius", "12px"],
  ["live tile needs fill", "background", "var(--amberTile)"],
  ["live tile running fill", "background", "var(--sunk)"],
  ["live name size", "font-size", "14px"],
  ["live sub size", "font-size", "12.5px"],
  ["live sub needs ink", "color", "var(--amberInk)"],
  ["progress track width", "width", "44px"],
  ["progress track height", "height", "5px"],
  ["progress track fill", "background", "var(--track)"],
  ["progress bar needs fill", "background", "var(--amber)"],
  ["progress bar running fill", "background", "var(--run)"],
  ["row hover fill", "background", "var(--rowHover)"],
  // divider
  ["divider height", "height", "1px"],
  ["divider fill", "background", "var(--line2)"],
  ["divider margin", "margin", "4px 10px"],
  // Up next
  ["event row columns", "grid-template-columns", "52px minmax(0, 1fr)"],
  ["event row padding", "padding", "8px 10px"],
  ["event row radius", "border-radius", "14px"],
  ["event time ink", "color", "var(--ink2)"],
  ["event title line height", "line-height", "1.3"],
  // September spend
  ["spend padding", "padding", "10px 10px 12px"],
  ["spend amount size", "font-size", "24px"],
  ["spend amount tracking", "letter-spacing", "-0.4px"],
  ["spend bar height", "height", "6px"],
  ["spend spent segment", "background", "var(--hero)"],
  ["spend waiting segment", "background", "var(--amber)"],
  ["spend waiting opacity", "opacity", "0.85"],
  // composer
  ["logo tile size", "width", "36px"],
  ["logo tile fill", "background", "var(--hero)"],
  ["input size", "font-size", "20px"],
  ["input weight", "font-weight", "700"],
  ["input height", "height", "58px"],
  ["start height", "height", "54px"],
  ["start padding", "padding", "0 24px"],
  ["start radius", "border-radius", "18px"],
  ["start fill", "background", "var(--hero)"],
  ["start ink", "color", "#FFFFFF"],
  ["start size", "font-size", "16px"],
  ["start hover", "filter", "brightness(1.08)"],
  ["size of job width", "width", "390px"],
  ["size of job track radius", "border-radius", "16px"],
  ["size of job item height", "height", "36px"],
  ["hint size", "font-size", "14px"],
  ["hint line height", "line-height", "1.35"],
  ["chip height", "height", "38px"],
  ["chip padding", "padding", "0 16px"],
  ["chip radius", "border-radius", "999px"],
  // drafting line and plan card
  ["drafting height", "height", "44px"],
  ["drafting padding", "padding", "0 18px 0 14px"],
  ["drafting fill", "background", "var(--pop)"],
  ["drafting border", "border", "1px solid var(--line2)"],
  ["plan radius", "border-radius", "24px"],
  ["plan padding", "padding", "18px 18px 18px 22px"],
  ["plan columns", "grid-template-columns", "minmax(0, 1fr) auto"],
  ["plan gap", "gap", "20px"],
  ["tier badge fill", "background", "var(--heroSoft)"],
  ["tier badge ink", "color", "var(--heroInk)"],
  ["tier badge height", "height", "24px"],
  ["tier badge radius", "border-radius", "7px"],
  ["tier badge tracking", "letter-spacing", "0.5px"],
  ["plan query size", "font-size", "17px"],
  ["plan meta gap", "gap", "22px"],
  ["plan meta label ink", "color", "var(--ink3)"],
  ["plan step ink", "color", "var(--ink2)"],
  ["step number size", "width", "20px"],
  ["step number fill", "background", "var(--chip)"],
  ["step number text", "font-size", "11.5px"],
  ["confirm height", "height", "46px"],
  ["confirm radius", "border-radius", "14px"],
  ["confirm padding", "padding", "0 22px"],
  ["change brief height", "height", "40px"],
  ["change brief border", "border", "1px solid var(--line)"],
  ["change brief fill", "background", "var(--btn2)"],
  // map pins
  ["pin fill", "background", "var(--pop)"],
  ["pin border", "border", "1px solid var(--line2)"],
  ["pin padding", "padding", "5px 16px 5px 5px"],
  ["pin icon size", "width", "34px"],
  ["pin name size", "font-size", "14.5px"],
  ["pin stem", "background", "var(--stem)"],
  ["pin dot", "background", "var(--pin)"],
  ["pin halo", "box-shadow", "0 0 0 5px var(--halo)"],
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

describe("WEB_4_home_styles: the glass panels (README 'Glass (nav and Home only)')", () => {
  it("WEB_4_home_styles_one_rule_holds_the_whole_glass_recipe", () => {
    const glass = parsed().rules.filter(
      (r) =>
        norm(r.decls.get("background") ?? r.decls.get("background-color")) === norm("var(--gBg)") &&
        norm(r.decls.get("backdrop-filter")) === norm("var(--gFx)") &&
        norm(r.decls.get("-webkit-backdrop-filter")) === norm("var(--gFx)") &&
        norm(r.decls.get("border")) === norm("1px solid var(--gBd)") &&
        norm(r.decls.get("box-shadow")) === norm("var(--sh)"),
    );
    expect(
      glass.length,
      "a rule with fill, border, blur (both spellings) and shadow",
    ).toBeGreaterThanOrEqual(1);
  });

  it("WEB_4_home_styles_the_h1_rule_is_Nunito_900_50px", () => {
    const h1 = parsed().rules.filter(
      (r) =>
        norm(r.decls.get("font-size")) === "50px" && norm(r.decls.get("font-weight")) === "900",
    );
    expect(h1.length).toBeGreaterThanOrEqual(1);
    expect(norm(h1[0]?.decls.get("font-family"))).toContain("nunito");
    expect(norm(h1[0]?.decls.get("font-family"))).not.toContain("nunito sans");
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
  // The rules of the `@media (max-width: 480px)` blocks that name the composer column.
  const phone = (): CssRule[] => {
    const blocks = css().match(/@media \(max-width: 480px\) \{[\s\S]*?\n\}/g) ?? [];
    return blocks
      .filter((b) => b.includes(".park-home-composer"))
      .flatMap((b) => parseRules(b).rules);
  };
  const decl = (selector: string, prop: string): string | undefined =>
    phone()
      .filter((r) => r.selector === selector)
      .map((r) => norm(r.decls.get(prop)))
      .filter((v) => v !== "")
      .pop();

  it("QA_13OCT_home_phone_root_is_a_scrolling_flex_column", () => {
    const root = "[data-park] .park-home-root";
    expect(decl(root, "display")).toBe("flex");
    expect(decl(root, "flex-direction")).toBe("column");
    expect(decl(root, "overflow-y")).toBe("auto");
  });

  it("QA_13OCT_home_phone_greeting_and_composer_columns_are_in_the_flow_not_pinned", () => {
    for (const sel of ["[data-park] .park-home-leftcol", "[data-park] .park-home-composer"]) {
      expect(decl(sel, "position"), sel).toBe("static");
      expect(decl(sel, "transform"), sel).toBe("none");
    }
    expect(decl("[data-park] .park-home-legal", "position")).toBe("static");
  });

  it("QA_13OCT_home_phone_input_takes_its_own_row_so_the_placeholder_is_not_cut", () => {
    expect(decl("[data-park] .park-home-input-row", "flex-wrap")).toBe("wrap");
    expect(decl("[data-park] .park-home-input", "flex")).toBe("1 1 100%");
  });
});
