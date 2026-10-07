// WEB-6 style spec: World.css is parsed and checked against the numbers of the reference page
// (design_handoff_tilo_web_app/design/Tilo App World.dc.html, inline styles, one block per element).
// Each BUNDLE below is one element of the reference: the declarations that block makes. A bundle passes when
// ONE class of World.css (all its plain rules merged; a `:hover` or modifier class is another group) carries
// every declaration, so a port that keeps one class per element passes, and a value that went missing or
// drifted fails. Layout-only declarations (display, align-items, justify-content, wrap) are left out on
// purpose: the real cascade, boxes and computed values are measured in the browser by e2e/park-world.spec.ts.
// The header buttons, Approve, Ask me later, Run now, See in Agenda, Open result, Share to Slack and Open
// live view may come from the core Button component: they are checked on the rendered page in
// World.styles.dom.test.tsx, whichever stylesheet declares them.
// Conventions of the Park pages (plan section 10): every selector under [data-park] and tied to the page by a
// `park-world-` class, colours as var(--token) except #F0A500 / #1F1D2B (needs) and #FFFFFF (on the hero fill)
// and the #5A3FE0 focus ring, no transition / animation / @keyframes (BQ-WEB-3: the `transition: width .5s`
// of the bars and the `tiloSpin` ring return with the motion restore), night comes from the tokens.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { type CssRule, norm, parseRules } from "../../../../test-support/park/componentsCss";
import { stripComments } from "../../../../test-support/park/css";

const CSS_PATH = join(__dirname, "World.css");
const css = () => readFileSync(CSS_PATH, "utf8");
const parsed = () => parseRules(css());

type Decls = Record<string, string>;

/** Plain rules merged per last class of the selector (`:hover` and other states are not part of it). */
function groups(rules: readonly CssRule[]): Map<string, Map<string, string>> {
  const out = new Map<string, Map<string, string>>();
  for (const r of rules) {
    const last =
      r.selector
        .replace(/^\[data-park\]\s*/, "")
        .split(" ")
        .pop() ?? "";
    if (!last || last.includes(":")) continue;
    const g = out.get(last) ?? new Map<string, string>();
    for (const [k, v] of r.decls) g.set(k, norm(v));
    out.set(last, g);
  }
  return out;
}
const value = (g: Map<string, string>, prop: string): string | undefined =>
  g.get(prop) ?? (prop === "background" ? g.get("background-color") : undefined);

/** The group that carries the most of the wanted declarations: for the failure message. */
function closest(rules: readonly CssRule[], want: Decls): string {
  let best = "no rule at all";
  let bestHits = -1;
  for (const [cls, g] of groups(rules)) {
    const hits = Object.entries(want).filter(([p, v]) => value(g, p) === norm(v)).length;
    if (hits > bestHits) {
      bestHits = hits;
      best = `${cls} has ${hits} of ${Object.keys(want).length}`;
    }
  }
  return best;
}

const BUNDLES: readonly [string, Decls][] = [
  // breadcrumb
  ["breadcrumb", { gap: "8px", "font-size": "14px", "font-weight": "700", color: "var(--ink3)" }],
  [
    "back link",
    {
      gap: "6px",
      height: "32px",
      padding: "0 10px 0 6px",
      "border-radius": "10px",
      color: "var(--ink2)",
    },
  ],
  // title block
  ["head row", { gap: "20px" }],
  [
    "eyebrow",
    { "font-size": "12px", "font-weight": "800", "letter-spacing": "0.7px", color: "var(--ink3)" },
  ],
  [
    "status chip",
    {
      height: "26px",
      padding: "0 10px",
      "border-radius": "8px",
      "font-size": "12.5px",
      "font-weight": "800",
      gap: "7px",
    },
  ],
  ["chip dot", { width: "7px", height: "7px", "border-radius": "99px" }],
  [
    "h1",
    {
      margin: "0",
      "font-weight": "900",
      "font-size": "36px",
      "letter-spacing": "-0.8px",
      "line-height": "1.05",
      "text-wrap": "balance",
    },
  ],
  ["meta", { margin: "0", "font-size": "15.5px", "font-weight": "600", color: "var(--ink2)" }],
  ["header buttons", { gap: "8px" }],
  // top grid, map card and map
  ["top grid", { "align-items": "start", gap: "18px" }],
  [
    "map card",
    {
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "22px",
      padding: "12px",
      gap: "12px",
    },
  ],
  [
    "map",
    {
      position: "relative",
      height: "440px",
      "border-radius": "16px",
      background: "var(--sunk)",
      overflow: "hidden",
    },
  ],
  [
    "hero tag",
    {
      position: "absolute",
      left: "14px",
      top: "14px",
      height: "32px",
      padding: "0 12px",
      "border-radius": "10px",
      background: "var(--pop)",
      "box-shadow": "var(--sh)",
      gap: "8px",
      "font-size": "13px",
      "font-weight": "800",
    },
  ],
  ["paused overlay", { position: "absolute", background: "var(--scrim)" }],
  [
    "paused pill",
    {
      height: "40px",
      padding: "0 16px",
      "border-radius": "12px",
      background: "var(--pop)",
      "box-shadow": "var(--sh)",
      gap: "8px",
      "font-size": "14px",
      "font-weight": "800",
    },
  ],
  ["progress row", { gap: "18px", padding: "2px 6px 4px" }],
  ["progress wrap", { flex: "1", "min-width": "200px", gap: "10px" }],
  [
    "progress track",
    {
      flex: "1",
      height: "6px",
      "border-radius": "99px",
      background: "var(--track)",
      overflow: "hidden",
    },
  ],
  [
    "progress label",
    { "font-size": "13.5px", "font-weight": "800", "min-width": "40px", "text-align": "right" },
  ],
  ["legend", { gap: "14px", "font-size": "12.5px", "font-weight": "700", color: "var(--ink2)" }],
  ["legend item", { gap: "6px" }],
  ["legend swatch", { width: "9px", height: "9px", "border-radius": "3px" }],
  // side column
  ["side column", { gap: "18px" }],
  [
    "waiting card",
    {
      background: "var(--amberSoft)",
      border: "1px solid var(--amberLine)",
      "border-radius": "22px",
      padding: "16px",
      gap: "12px",
    },
  ],
  ["waiting head", { gap: "10px" }],
  [
    "waiting tile",
    {
      width: "36px",
      height: "36px",
      "border-radius": "11px",
      background: "var(--amberTile)",
      overflow: "hidden",
    },
  ],
  [
    "waiting label",
    {
      "font-size": "12px",
      "font-weight": "800",
      "letter-spacing": "0.6px",
      color: "var(--amberInk)",
    },
  ],
  ["waiting title", { "font-size": "15px", "font-weight": "800" }],
  [
    "decision card",
    { background: "var(--card)", "border-radius": "14px", padding: "12px 14px", gap: "10px" },
  ],
  ["decision title", { "font-size": "14px", "font-weight": "800" }],
  ["decision body", { "font-size": "13px", "font-weight": "600", color: "var(--ink2)" }],
  ["decision buttons", { gap: "8px" }],
  [
    "decision done",
    { "font-size": "13px", "font-weight": "800", color: "var(--okInk)", gap: "6px" },
  ],
  [
    "spend card",
    {
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "22px",
      padding: "18px 18px 16px",
      gap: "12px",
    },
  ],
  ["spend title", { "font-size": "15px", "font-weight": "800" }],
  ["spend link", { "font-size": "13.5px" }],
  ["spend value", { "font-size": "28px", "font-weight": "800", "letter-spacing": "-0.5px" }],
  ["spend of", { "font-size": "14px", "font-weight": "700", color: "var(--ink2)" }],
  [
    "spend bar",
    { height: "8px", "border-radius": "99px", background: "var(--track)", overflow: "hidden" },
  ],
  ["spend bar fill", { height: "100%", background: "var(--hero)", "border-radius": "99px" }],
  [
    "spend note",
    { "font-size": "13px", "font-weight": "700", color: "var(--ink2)", "line-height": "1.4" },
  ],
  [
    "facts card",
    {
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "22px",
      padding: "8px 18px",
    },
  ],
  [
    "fact row",
    {
      "grid-template-columns": "96px minmax(0, 1fr)",
      gap: "12px",
      "min-height": "44px",
      padding: "6px 0",
      "border-bottom": "1px solid var(--line2)",
    },
  ],
  ["fact key", { "font-size": "13px", "font-weight": "700", color: "var(--ink3)" }],
  ["fact value", { "font-size": "14px", "font-weight": "800" }],
  [
    "skills row",
    { "grid-template-columns": "96px minmax(0, 1fr)", gap: "12px", padding: "12px 0 8px" },
  ],
  [
    "tools row",
    { "grid-template-columns": "96px minmax(0, 1fr)", gap: "12px", padding: "4px 0 14px" },
  ],
  [
    "row label",
    { "padding-top": "5px", "font-size": "13px", "font-weight": "700", color: "var(--ink3)" },
  ],
  ["chips", { gap: "6px" }],
  [
    "skill chip",
    {
      height: "28px",
      padding: "0 10px",
      border: "0",
      "border-radius": "8px",
      background: "var(--heroSoft)",
      color: "var(--heroInk)",
      "font-size": "12.5px",
      "font-weight": "800",
      gap: "6px",
    },
  ],
  [
    "tool chip",
    {
      height: "28px",
      padding: "0 10px 0 4px",
      border: "1px solid var(--line)",
      "border-radius": "8px",
      background: "var(--btn2)",
      color: "var(--ink)",
      "font-size": "12.5px",
      "font-weight": "800",
      gap: "6px",
    },
  ],
  [
    "tool monogram",
    {
      width: "20px",
      height: "20px",
      "border-radius": "6px",
      background: "var(--sunk)",
      "font-size": "10.5px",
      "font-weight": "900",
    },
  ],
  [
    "no skills",
    { "font-size": "13.5px", "font-weight": "700", color: "var(--ink3)", "padding-top": "5px" },
  ],
  // lower grid and its sections
  [
    "lower grid",
    {
      "grid-template-columns": "repeat(auto-fit, minmax(min(100%, 420px), 1fr))",
      gap: "18px",
      "align-items": "start",
    },
  ],
  [
    "section card",
    {
      background: "var(--card)",
      border: "1px solid var(--line2)",
      "border-radius": "22px",
      padding: "18px 18px 10px",
      gap: "4px",
    },
  ],
  ["section head", { padding: "0 4px 8px" }],
  ["section h2", { margin: "0", "font-size": "17px", "font-weight": "800" }],
  ["section sub", { "font-size": "13px", "font-weight": "700", color: "var(--ink3)" }],
  [
    "district row",
    {
      "grid-template-columns": "40px minmax(0, 1fr) 110px auto",
      gap: "14px",
      padding: "10px 4px",
      "border-top": "1px solid var(--line2)",
    },
  ],
  ["district tile", { width: "40px", height: "40px", "border-radius": "12px" }],
  ["district name", { "font-size": "14.5px", "font-weight": "800" }],
  [
    "district note",
    {
      "font-size": "13px",
      "font-weight": "600",
      color: "var(--ink2)",
      "white-space": "nowrap",
      overflow: "hidden",
      "text-overflow": "ellipsis",
    },
  ],
  ["district count", { "font-size": "12.5px", "font-weight": "700", color: "var(--ink2)" }],
  [
    "district bar",
    { height: "5px", "border-radius": "99px", background: "var(--track)", overflow: "hidden" },
  ],
  [
    "district chip",
    {
      height: "24px",
      padding: "0 9px",
      "border-radius": "7px",
      "font-size": "12px",
      "font-weight": "800",
    },
  ],
  [
    "run row",
    {
      "grid-template-columns": "32px minmax(0, 1fr) auto",
      gap: "12px",
      padding: "11px 4px",
      "border-top": "1px solid var(--line2)",
    },
  ],
  ["run tile", { width: "32px", height: "32px", "border-radius": "10px" }],
  ["run what", { "font-size": "14.5px", "font-weight": "800" }],
  ["run when", { "font-size": "13px", "font-weight": "600", color: "var(--ink2)" }],
  ["run cost", { "font-size": "14px", "font-weight": "800" }],
  [
    "no runs",
    {
      padding: "18px 4px",
      "border-top": "1px solid var(--line2)",
      "font-size": "14px",
      "font-weight": "600",
      color: "var(--ink2)",
    },
  ],
  ["run actions", { gap: "8px", padding: "12px 4px 8px", "border-top": "1px solid var(--line2)" }],
  [
    "result body",
    { "border-top": "1px solid var(--line2)", padding: "14px 4px 12px", gap: "14px" },
  ],
  [
    "result out",
    {
      "border-radius": "14px",
      background: "var(--sunk)",
      padding: "16px 18px",
      "font-size": "15px",
      "font-weight": "700",
      "line-height": "1.5",
    },
  ],
  [
    "result running",
    { gap: "10px", "font-size": "13.5px", "font-weight": "700", color: "var(--ink2)" },
  ],
  [
    "spinner (still)",
    {
      width: "16px",
      height: "16px",
      "box-sizing": "border-box",
      "border-radius": "99px",
      border: "2.5px solid var(--track)",
      "border-top-color": "var(--hero)",
    },
  ],
  [
    "activity row",
    {
      "grid-template-columns": "36px minmax(0, 1fr) auto",
      gap: "12px",
      padding: "10px 4px",
      "border-top": "1px solid var(--line2)",
    },
  ],
  [
    "activity avatar",
    {
      width: "36px",
      height: "36px",
      "border-radius": "11px",
      background: "var(--sunk)",
      overflow: "hidden",
      "font-size": "12px",
      "font-weight": "800",
    },
  ],
  ["activity who", { "font-size": "13px", "font-weight": "800", color: "var(--ink2)", gap: "6px" }],
  ["activity dot", { width: "7px", height: "7px", "border-radius": "99px" }],
  ["activity text", { "font-size": "14px", "font-weight": "600" }],
  [
    "activity time",
    { "font-size": "12.5px", "font-weight": "700", color: "var(--ink3)", "white-space": "nowrap" },
  ],
];

describe("WEB_6_world_styles: World.css exists and follows the Park conventions", () => {
  it("WEB_6_world_styles_World_css_exists_and_WorldPage_imports_it", () => {
    expect(existsSync(CSS_PATH), "src/park/pages/World/World.css").toBe(true);
    const page = readFileSync(join(__dirname, "WorldPage.tsx"), "utf8");
    expect(page).toMatch(/import\s+["']\.\/World\.css["']/);
  });

  it("WEB_6_world_styles_every_selector_is_under_data_park_and_tied_to_a_park_world_class", () => {
    const { rules } = parsed();
    expect(rules.length).toBeGreaterThan(30);
    for (const r of rules) {
      expect(r.selector, r.selector).toMatch(/^\[data-park\]/);
      expect(r.selector, `${r.selector} must carry a park-world- class`).toMatch(
        /\.park-world-[\w-]+/,
      );
    }
  });

  it("WEB_6_world_styles_no_transition_animation_keyframes_or_will_change", () => {
    const text = stripComments(css());
    expect(text).not.toMatch(/\btransition\b|\banimation\b|@keyframes|will-change/i);
    expect(parsed().others.map((o) => o.head)).toEqual([]);
  });

  it("WEB_6_world_styles_colours_are_tokens_except_the_ones_the_README_hard_codes", () => {
    const text = stripComments(css());
    const hex = [...text.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0].toUpperCase());
    for (const h of hex)
      expect(["#F0A500", "#1F1D2B", "#FFFFFF", "#5A3FE0"], `hard-coded ${h}`).toContain(h);
    expect([...text.matchAll(/rgba?\([^)]*\)/g)].map((m) => m[0])).toEqual([]);
  });

  it("WEB_6_world_styles_night_comes_from_the_tokens_not_from_overrides_here", () => {
    expect(stripComments(css())).not.toMatch(/data-time/);
  });

  it("WEB_6_world_styles_the_page_overrides_the_sheet_padding_to_24_32_36_under_its_root", () => {
    // PageSheet pads 28 32 36 (plan 8c: World has 24 on top). The override sits under the page's own root class.
    const hit = parsed().rules.filter(
      (r) =>
        /\.park-world-[\w-]+\s+\.park-sheet$/.test(r.selector) &&
        norm(r.decls.get("padding")) === "24px 32px 36px",
    );
    expect(
      hit.length,
      "[data-park] .park-world-<root> .park-sheet { padding: 24px 32px 36px }",
    ).toBeGreaterThanOrEqual(1);
  });

  it("WEB_6_world_styles_the_h1_is_Nunito_900_36px", () => {
    const h1 = [...groups(parsed().rules).values()].filter(
      (g) => g.get("font-size") === "36px" && g.get("font-weight") === "900",
    );
    expect(h1.length).toBeGreaterThanOrEqual(1);
    expect(h1[0]?.get("font-family")).toContain("nunito");
    expect(h1[0]?.get("font-family")).not.toContain("nunito sans");
  });
});

describe("WEB_6_world_styles: every block of the reference's inline styles", () => {
  it.each(BUNDLES)("WEB_6_world_styles_%s", (_what, want) => {
    const rules = parsed().rules;
    const ok = [...groups(rules).values()].some((g) =>
      Object.entries(want).every(([p, v]) => value(g, p) === norm(v)),
    );
    expect(
      ok,
      `no single class carries ${JSON.stringify(want)}; closest: ${closest(rules, want)}`,
    ).toBe(true);
  });
});

describe("WEB_6_world_styles: states are states, not motion", () => {
  it("WEB_6_world_styles_the_back_link_hovers_to_chip_and_ink", () => {
    const hover = parsed().rules.filter((r) => /:hover/.test(r.selector));
    const ok = hover.some(
      (r) =>
        norm(r.decls.get("background")) === "var(--chip)" &&
        norm(r.decls.get("color")) === "var(--ink)",
    );
    expect(ok, "reference style-hover: background var(--chip); color var(--ink)").toBe(true);
  });

  it("WEB_6_world_styles_links_and_chips_carry_the_README_focus_ring", () => {
    const ring = parsed().rules.filter(
      (r) =>
        /:focus-visible/.test(r.selector) &&
        norm(r.decls.get("outline")) === "3px solid #5a3fe0" &&
        norm(r.decls.get("outline-offset")) === "2px",
    );
    expect(ring.length, "a :focus-visible rule with the 3px #5A3FE0 ring").toBeGreaterThanOrEqual(
      1,
    );
  });
});
