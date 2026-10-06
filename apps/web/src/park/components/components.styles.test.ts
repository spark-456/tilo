// WEB-2 style spec: park.components.css is parsed and checked against the numbers the handoff README
// pins in "Core components (build these first)", "Shape and spacing" and "Typography". Ranges where the
// README gives ranges (h38-42, r11-12, ...). The reader and its conventions (single-class compounds under
// [data-park], literal values, README shorthands) are in test-support/park/componentsCss.ts.
// Real computed styles in a browser are checked again in e2e/park-components.spec.ts.
//
// Motion: the README gives a hover brightness, a sliding thumb (.4s) and a knob (.25s). They are NOT built
// here (BQ-WEB-3, ADR-0003a 5): the stylesheet has no transition, animation or @keyframes, and the visual end
// state is built. The one pinned exception is hover `filter`, which is a state, not motion.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  COMPONENTS_CSS,
  COMPONENTS_DIR,
  type CssRule,
  declsFor,
  norm,
  numbers,
  parseRules,
  pick,
  readComponentsCss,
} from "../../../test-support/park/componentsCss";
import { propsFor, stripComments } from "../../../test-support/park/css";
import { HANDOFF_TOKENS_PATH } from "../../../test-support/park/prototype";

const css = (): string => readComponentsCss();
let cache: ReturnType<typeof parseRules> | undefined;
const parsed = () => {
  cache ??= parseRules(css());
  return cache;
};
const rules = (): CssRule[] => parsed().rules;

type Alias = "background" | "border-radius" | "box-shadow" | string;
const PROP: Record<string, string[]> = {
  background: ["background", "background-color"],
};
const val = (classes: string[], prop: Alias, state = "", ancestors: string[] = []): string =>
  pick(declsFor(rules(), classes, state, ancestors), ...(PROP[prop] ?? [prop]));

/** Pins `prop` of an element with `classes` to exactly `expected` (compared after normalisation). */
function pin(
  classes: string[],
  prop: Alias,
  expected: string,
  state = "",
  ancestors: string[] = [],
): void {
  const where = `${ancestors.map((a) => `.${a} `).join("")}${classes.join(".")} ${state} ${prop}`;
  expect(val(classes, prop, state, ancestors), where).toBe(norm(expected));
}

/** Pins `prop` to one of several accepted spellings ("" means not declared). */
function pinOneOf(classes: string[], prop: Alias, accepted: string[]): void {
  expect(accepted.map(norm), `${classes.join(".")} ${prop}`).toContain(val(classes, prop));
}

/** Pins the first number of `prop` to lie in [lo, hi]. */
function range(classes: string[], prop: Alias, lo: number, hi: number): void {
  const v = val(classes, prop);
  const n = numbers(v)[0];
  expect(n, `${classes.join(".")} ${prop} is declared (got "${v}")`).toBeDefined();
  expect(n as number, `${classes.join(".")} ${prop}: ${v}`).toBeGreaterThanOrEqual(lo);
  expect(n as number, `${classes.join(".")} ${prop}: ${v}`).toBeLessThanOrEqual(hi);
}

/** Every number of a multi-value property (padding) lies in [lo, hi]. */
function rangeAll(classes: string[], prop: Alias, lo: number, hi: number): void {
  const v = val(classes, prop);
  const ns = numbers(v);
  expect(ns.length, `${classes.join(".")} ${prop} is declared (got "${v}")`).toBeGreaterThan(0);
  for (const n of ns) {
    expect(n, `${classes.join(".")} ${prop}: ${v}`).toBeGreaterThanOrEqual(lo);
    expect(n, `${classes.join(".")} ${prop}: ${v}`).toBeLessThanOrEqual(hi);
  }
}

const SHADOW_SEG = "0 1px 3px rgba(31,29,43,.16)";
const SHADOW_KNOB = "0 1px 3px rgba(31,29,43,.3)";

describe("WEB_2_styles_stylesheet: one file, scoped, token-driven, still", () => {
  it("WEB_2_styles_the_one_stylesheet_exists_and_is_the_only_css_file_in_components_and_dev", () => {
    expect(fs.existsSync(COMPONENTS_CSS), `${COMPONENTS_CSS} must exist`).toBe(true);
    const cssFiles = [COMPONENTS_DIR, path.join(COMPONENTS_DIR, "..", "dev")].flatMap((dir) =>
      fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith(".css")) : [],
    );
    expect(cssFiles).toEqual(["park.components.css"]);
  });

  it("WEB_2_styles_a_component_imports_the_stylesheet", () => {
    const sources = fs
      .readdirSync(COMPONENTS_DIR)
      .filter((f) => /\.tsx?$/.test(f) && !/\.test\./.test(f))
      .map((f) => fs.readFileSync(path.join(COMPONENTS_DIR, f), "utf8"));
    expect(sources.some((s) => /import\s+["']\.\/park\.components\.css["']/.test(s))).toBe(true);
  });

  it("WEB_2_styles_every_selector_starts_with_data_park", () => {
    const { rules: rs } = parsed();
    expect(rs.length).toBeGreaterThan(30);
    expect(rs.filter((r) => !r.selector.startsWith("[data-park]")).map((r) => r.selector)).toEqual(
      [],
    );
  });

  it("WEB_2_styles_no_transition_animation_or_keyframes_anywhere_honesty_FR_WLD_09", () => {
    const body = stripComments(css());
    expect(body).not.toMatch(/@keyframes/i);
    expect(body).not.toMatch(/(?:^|[\s{;])(?:transition|animation)(?:-[a-z-]+)?\s*:/im);
    expect(body).not.toMatch(/\bwill-change\b/);
    expect(body).not.toMatch(/scroll-behavior\s*:\s*smooth/);
    const decls = rules().flatMap((r) => [...r.decls.keys()]);
    expect(decls.filter((d) => /^(?:transition|animation)/.test(d))).toEqual([]);
  });

  it("WEB_2_styles_only_media_and_supports_at_rules_no_import_font_face_or_keyframes", () => {
    expect(parsed().others.map((o) => o.head)).toEqual([]);
    expect(stripComments(css())).not.toMatch(/@import\b/);
  });

  it("WEB_2_styles_no_night_selector_the_theme_comes_from_the_tokens", () => {
    expect(stripComments(css())).not.toMatch(/data-time/);
  });

  it("WEB_2_styles_uses_only_handoff_token_names_and_declares_no_custom_properties", () => {
    const handoff = fs.readFileSync(HANDOFF_TOKENS_PATH, "utf8");
    const known = new Set(propsFor(handoff, ":root").keys());
    const used = new Set(
      [...stripComments(css()).matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1] as string),
    );
    expect(used.size, "the stylesheet reads tokens").toBeGreaterThan(15);
    expect([...used].filter((n) => !known.has(n))).toEqual([]);
    const declared = rules().flatMap((r) => [...r.decls.keys()].filter((d) => d.startsWith("--")));
    expect(declared, "literal values, so the spec above can read them").toEqual([]);
  });

  it("WEB_2_styles_hard_coded_hex_colours_are_only_the_README_ones", () => {
    const allowed = new Set(["#ffffff", "#f0a500", "#1f1d2b", "#1e8a4c", "#5a3fe0"]);
    const found = [...stripComments(css()).matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => norm(m[0]));
    expect(found.filter((h) => !allowed.has(h))).toEqual([]);
  });
});

describe("WEB_2_styles_focus: the focus ring is 3px solid #5A3FE0, offset 2px", () => {
  const INTERACTIVE: Array<[string, string[]]> = [
    ["button primary", ["park-btn", "park-btn--primary", "park-btn--md"]],
    ["button secondary", ["park-btn", "park-btn--secondary", "park-btn--md"]],
    ["button needs", ["park-btn", "park-btn--needs", "park-btn--md"]],
    ["switch", ["park-switch"]],
    ["segmented item", ["park-seg__item"]],
    ["list row", ["park-row", "park-row--action"]],
    ["kpi tile", ["park-kpi"]],
    ["menu row", ["park-menu__row"]],
    ["toast action", ["park-toast__action"]],
  ];
  it.each(INTERACTIVE)("WEB_2_styles_focus_ring_on_%s", (_name, classes) => {
    pin(classes, "outline", "3px solid #5A3FE0", ":focus-visible");
    pin(classes, "outline-offset", "2px", ":focus-visible");
  });
});

describe("WEB_2_styles_button", () => {
  const PRIMARY = ["park-btn", "park-btn--primary", "park-btn--md"];
  it("WEB_2_styles_button_primary_h42_r12_hero_white_15px_800_padding_0_18", () => {
    pin(PRIMARY, "height", "42px");
    pin(PRIMARY, "border-radius", "12px");
    pin(PRIMARY, "background", "var(--hero)");
    pin(PRIMARY, "color", "#FFF");
    pin(PRIMARY, "font-size", "15px");
    pin(PRIMARY, "font-weight", "800");
    pin(PRIMARY, "padding", "0 18px");
  });

  it("WEB_2_styles_button_primary_with_an_icon_has_padding_0_14", () => {
    pin([...PRIMARY, "park-btn--icon"], "padding", "0 14px");
  });

  it("WEB_2_styles_button_primary_hover_is_filter_brightness_1_08", () => {
    pin(PRIMARY, "filter", "brightness(1.08)", ":hover");
  });

  it.each(["sm", "md"])(
    "WEB_2_styles_button_secondary_%s_h38_42_r11_12_btn2_line_ink_14_14_5px_800",
    (size) => {
      const c = ["park-btn", "park-btn--secondary", `park-btn--${size}`];
      range(c, "height", 38, 42);
      range(c, "border-radius", 11, 12);
      pin(c, "background", "var(--btn2)");
      pin(c, "border", "1px solid var(--line)");
      pin(c, "color", "var(--ink)");
      range(c, "font-size", 14, 14.5);
      pin(c, "font-weight", "800");
    },
  );

  it.each(["sm", "md"])(
    "WEB_2_styles_button_needs_%s_h28_36_r8_11_amber_ink_12_5_14px_800",
    (size) => {
      const c = ["park-btn", "park-btn--needs", `park-btn--${size}`];
      range(c, "height", 28, 36);
      range(c, "border-radius", 8, 11);
      pin(c, "background", "#F0A500");
      pin(c, "color", "#1F1D2B");
      range(c, "font-size", 12.5, 14);
      pin(c, "font-weight", "800");
    },
  );

  it("WEB_2_styles_button_needs_amber_is_hard_coded_not_a_token_in_both_themes", () => {
    expect(val(["park-btn", "park-btn--needs", "park-btn--md"], "background")).not.toContain(
      "var(",
    );
    expect(val(["park-btn", "park-btn--needs", "park-btn--md"], "color")).not.toContain("var(");
  });
});

describe("WEB_2_styles_segmented", () => {
  const SLIDE_TRACK = ["park-seg", "park-seg--sliding"];
  const SLIDE_ITEM = ["park-seg__item", "park-seg__item--slide"];

  it("WEB_2_styles_segmented_track_seg_r12_p3_gap2", () => {
    pin(["park-seg"], "background", "var(--seg)");
    pin(["park-seg"], "border-radius", "12px");
    pin(["park-seg"], "padding", "3px");
    pin(["park-seg"], "gap", "2px");
  });

  it("WEB_2_styles_segmented_plain_item_h32_r9_13px_800_padding_0_11px_ink2", () => {
    // Reference (Ledger "Entry type"): padding 0 11px, 13px. The README's 13.5px is the type table's range.
    const c = ["park-seg__item"];
    pin(c, "height", "32px");
    pin(c, "border-radius", "9px");
    pin(c, "font-size", "13px");
    pin(c, "font-weight", "800");
    pin(c, "padding", "0 11px");
    pin(c, "color", "var(--ink2)");
  });

  it("WEB_2_styles_segmented_selected_is_tabOn_with_the_small_shadow_and_ink_text", () => {
    const c = ["park-seg__item", "park-seg__item--on"];
    pin(c, "background", "var(--tabOn)");
    pin(c, "box-shadow", SHADOW_SEG);
    pin(c, "color", "var(--ink)");
  });

  it("WEB_2_styles_segmented_sliding_track_is_a_relative_grid_with_no_gap", () => {
    pin(SLIDE_TRACK, "position", "relative");
    pin(SLIDE_TRACK, "display", "grid");
    pin(SLIDE_TRACK, "background", "var(--seg)");
    pin(SLIDE_TRACK, "border-radius", "12px");
    pin(SLIDE_TRACK, "padding", "3px");
    pinOneOf(SLIDE_TRACK, "gap", ["", "0", "normal"]);
    pinOneOf(SLIDE_TRACK, "column-gap", ["", "0", "normal"]);
  });

  it("WEB_2_styles_segmented_sliding_thumb_is_inset_3px_all_round_and_carries_the_white", () => {
    const t = ["park-seg__thumb"];
    pin(t, "position", "absolute");
    pin(t, "top", "3px");
    pin(t, "bottom", "3px");
    pin(t, "left", "3px");
    pin(t, "background", "var(--tabOn)");
    pin(t, "box-shadow", SHADOW_SEG);
    pin(t, "border-radius", "9px");
  });

  it("WEB_2_styles_segmented_sliding_item_is_flat_h32_13px_800_no_radius_no_background", () => {
    pin(SLIDE_ITEM, "position", "relative");
    pin(SLIDE_ITEM, "height", "32px");
    pin(SLIDE_ITEM, "border", "0");
    pin(SLIDE_ITEM, "background", "transparent");
    pin(SLIDE_ITEM, "font-weight", "800");
    pin(SLIDE_ITEM, "font-size", "13px");
    pinOneOf(SLIDE_ITEM, "border-radius", ["", "0", "none"]);
    pinOneOf(SLIDE_ITEM, "box-shadow", ["", "none"]);
    pin(SLIDE_ITEM, "color", "var(--ink2)");
  });

  it.each([
    ["ink", "var(--ink)"],
    ["ink2", "var(--ink2)"],
    ["sch", "var(--sch)"],
    ["heroInk", "var(--heroInk)"],
    ["amberInk", "var(--amberInk)"],
  ])("WEB_2_styles_segmented_selected_sliding_label_tone_%s", (tone, colour) => {
    const c = [...SLIDE_ITEM, `park-seg__item--${tone}`];
    pin(c, "color", colour);
    pin(c, "background", "transparent");
    pinOneOf(c, "box-shadow", ["", "none"]);
  });

  it("WEB_2_styles_segmented_size_lg_is_h34_14px_for_plain_and_sliding_items", () => {
    for (const c of [
      ["park-seg__item", "park-seg__item--lg"],
      [...SLIDE_ITEM, "park-seg__item--lg"],
    ]) {
      pin(c, "height", "34px");
      pin(c, "font-size", "14px");
    }
  });
});

describe("WEB_2_styles_switch", () => {
  it("WEB_2_styles_switch_44x26_r99_padding3_off_is_track", () => {
    const c = ["park-switch"];
    pin(c, "width", "44px");
    pin(c, "height", "26px");
    pin(c, "border-radius", "99px");
    pin(c, "padding", "3px");
    pin(c, "background", "var(--track)");
  });

  it("WEB_2_styles_switch_on_is_ok", () => {
    pin(["park-switch", "park-switch--on"], "background", "var(--ok)");
  });

  it("WEB_2_styles_switch_knob_20_white_round_with_the_knob_shadow", () => {
    const c = ["park-switch__knob"];
    pin(c, "width", "20px");
    pin(c, "height", "20px");
    pin(c, "background", "#FFF");
    pin(c, "box-shadow", SHADOW_KNOB);
    const r = val(c, "border-radius");
    expect(r === "50%" || (numbers(r)[0] ?? 0) >= 10, `knob is round: ${r}`).toBe(true);
  });

  it("WEB_2_styles_switch_knob_on_is_translateX_18px_off_is_not_moved", () => {
    pin(["park-switch__knob", "park-switch__knob--on"], "transform", "translateX(18px)");
    const off = val(["park-switch__knob"], "transform");
    expect(["", "none", "translatex(0)", "translatex(0px)"]).toContain(off);
  });
});

describe("WEB_2_styles_chip_and_pill", () => {
  it("WEB_2_styles_chip_h22_24_r7_11_5_12px_800", () => {
    const c = ["park-chip"];
    range(c, "height", 22, 24);
    pin(c, "border-radius", "7px");
    range(c, "font-size", 11.5, 12);
    pin(c, "font-weight", "800");
  });

  it("WEB_2_styles_chip_md_is_24px_padding_0_9px_12px_r7_800", () => {
    const c = ["park-chip", "park-chip--ok"];
    pin(c, "height", "24px");
    pin(c, "padding", "0 9px");
    pin(c, "font-size", "12px");
    pin(c, "border-radius", "7px");
    pin(c, "font-weight", "800");
  });

  it("WEB_2_styles_chip_sm_is_22px_padding_0_8px_11_5px_r7_800_flex_nowrap", () => {
    // Reference: Skills list rows.
    const c = ["park-chip", "park-chip--ok", "park-chip--sm"];
    pin(c, "height", "22px");
    pin(c, "padding", "0 8px");
    pin(c, "font-size", "11.5px");
    pin(c, "border-radius", "7px");
    pin(c, "font-weight", "800");
    pin(c, "display", "flex");
    pin(c, "align-items", "center");
    pin(c, "white-space", "nowrap");
  });

  it.each(["ok", "hero", "amber", "neutral"])(
    "WEB_2_styles_chip_sm_keeps_the_%s_tone_colours",
    (tone) => {
      const sm = ["park-chip", `park-chip--${tone}`, "park-chip--sm"];
      const md = ["park-chip", `park-chip--${tone}`];
      expect(val(sm, "background")).toBe(val(md, "background"));
      expect(val(sm, "color")).toBe(val(md, "color"));
    },
  );

  it.each([
    ["ok", "var(--okSoft)", "var(--okInk)"],
    ["hero", "var(--heroSoft)", "var(--heroInk)"],
    ["amber", "var(--amberTile)", "var(--amberInk)"],
    ["neutral", "var(--chip)", "var(--ink2)"],
  ])("WEB_2_styles_chip_tone_%s_pair", (tone, bg, ink) => {
    const c = ["park-chip", `park-chip--${tone}`];
    pin(c, "background", bg);
    pin(c, "color", ink);
  });

  it("WEB_2_styles_pill_h30_r999_13_5px_800", () => {
    const c = ["park-pill"];
    pin(c, "height", "30px");
    pin(c, "border-radius", "999px");
    pin(c, "font-size", "13.5px");
    pin(c, "font-weight", "800");
  });

  it.each(["ok", "hero", "amber", "neutral"])(
    "WEB_2_styles_pill_tone_%s_sets_a_token_background_and_colour",
    (tone) => {
      const c = ["park-pill", `park-pill--${tone}`];
      expect(val(c, "background")).toMatch(/var\(--/);
      expect(val(c, "color")).toMatch(/var\(--/);
    },
  );
});

describe("WEB_2_styles_kpi", () => {
  it("WEB_2_styles_kpi_tile_r18_padding_16_18", () => {
    pin(["park-kpi"], "border-radius", "18px");
    pin(["park-kpi"], "padding", "16px 18px");
  });

  it("WEB_2_styles_kpi_label_13_800_value_28_800_minus_0_6px_sub_13_700", () => {
    pin(["park-kpi__label"], "font-size", "13px");
    pin(["park-kpi__label"], "font-weight", "800");
    pin(["park-kpi__value"], "font-size", "28px");
    pin(["park-kpi__value"], "font-weight", "800");
    pin(["park-kpi__value"], "letter-spacing", "-0.6px");
    pin(["park-kpi__sub"], "font-size", "13px");
    pin(["park-kpi__sub"], "font-weight", "700");
  });

  it.each(["amber", "ok"])("WEB_2_styles_kpi_tone_%s_sets_a_token_background", (tone) => {
    expect(val(["park-kpi", `park-kpi--${tone}`], "background")).toMatch(/var\(--/);
  });

  describe("tone sch (Ledger 'Saved by memory')", () => {
    const TILE = ["park-kpi", "park-kpi--sch"];
    const IN = ["park-kpi--sch"];

    it("WEB_2_styles_kpi_sch_tile_is_schSoft_with_a_transparent_1px_border_and_the_usual_box", () => {
      pin(TILE, "background", "var(--schSoft)");
      const d = declsFor(rules(), TILE);
      const border = pick(d, "border");
      const colour = pick(d, "border-color");
      expect(
        border === "1px solid transparent" ||
          (/^1px solid /.test(border) && colour === "transparent"),
        `border: ${border} / border-color: ${colour}`,
      ).toBe(true);
      pin(TILE, "border-radius", "18px");
      pin(TILE, "padding", "16px 18px");
      pin(TILE, "gap", "4px");
    });

    it("WEB_2_styles_kpi_sch_label_is_sch_13px_800", () => {
      pin(["park-kpi__label"], "color", "var(--sch)", "", IN);
      pin(["park-kpi__label"], "font-size", "13px", "", IN);
      pin(["park-kpi__label"], "font-weight", "800", "", IN);
    });

    it("WEB_2_styles_kpi_sch_value_is_ink_28px_800_minus_0_6px", () => {
      pin(["park-kpi__value"], "color", "var(--ink)", "", IN);
      pin(["park-kpi__value"], "font-size", "28px", "", IN);
      pin(["park-kpi__value"], "font-weight", "800", "", IN);
      pin(["park-kpi__value"], "letter-spacing", "-0.6px", "", IN);
    });

    it("WEB_2_styles_kpi_sch_sub_is_ink2_13px_700", () => {
      pin(["park-kpi__sub"], "color", "var(--ink2)", "", IN);
      pin(["park-kpi__sub"], "font-size", "13px", "", IN);
      pin(["park-kpi__sub"], "font-weight", "700", "", IN);
    });
  });
});

describe("WEB_2_styles_list_row", () => {
  it("WEB_2_styles_list_row_grid_44px_1fr_auto_gap12_padding8_10_r16", () => {
    const c = ["park-row"];
    pin(c, "display", "grid");
    pin(c, "grid-template-columns", "44px 1fr auto");
    pin(c, "gap", "12px");
    rangeAll(c, "padding", 8, 10);
    pin(c, "border-radius", "16px");
  });

  it("WEB_2_styles_list_row_trail_is_a_column_with_gap_3_and_the_cost_line_is_12px_700_ink3", () => {
    // Reference (Skills list rows): a small chip over the cost, 22 + 3 + the 12px line = 41px.
    pin(["park-row__trail"], "display", "flex");
    pin(["park-row__trail"], "flex-direction", "column");
    pin(["park-row__trail"], "gap", "3px");
    pin(["park-row__cost"], "font-size", "12px");
    pin(["park-row__cost"], "font-weight", "700");
    pin(["park-row__cost"], "color", "var(--ink3)");
    pin(["park-row__cost"], "white-space", "nowrap");
  });

  it("WEB_2_styles_list_row_hover_is_rowHover_and_selected_is_rowOn", () => {
    pin(["park-row", "park-row--action"], "background", "var(--rowHover)", ":hover");
    pin(["park-row", "park-row--on"], "background", "var(--rowOn)");
  });
});

describe("WEB_2_styles_art_tile", () => {
  it("WEB_2_styles_art_tile_aligns_art_to_the_bottom_edge_r12_18_clips", () => {
    const c = ["park-art"];
    pin(c, "display", "flex");
    pin(c, "align-items", "flex-end");
    pin(c, "overflow", "hidden");
    range(c, "border-radius", 12, 18);
  });

  it("WEB_2_styles_art_tile_sunk_is_the_default_tint", () => {
    pin(["park-art", "park-art--sunk"], "background", "var(--sunk)");
  });

  it.each(["hero", "amber", "ok", "blue", "pink", "orange", "green"])(
    "WEB_2_styles_art_tile_tint_%s_sets_a_token_background",
    (tint) => {
      expect(val(["park-art", `park-art--${tint}`], "background")).toMatch(/var\(--/);
    },
  );
});

describe("WEB_2_styles_card_and_sheet", () => {
  it("WEB_2_styles_card_card_line2_r22_padding_18_22", () => {
    const c = ["park-card"];
    pin(c, "background", "var(--card)");
    pin(c, "border", "1px solid var(--line2)");
    pin(c, "border-radius", "22px");
    rangeAll(c, "padding", 18, 22);
  });

  it("WEB_2_styles_page_sheet_sheet_gBd_r28_sh_padding_28_32_36", () => {
    const c = ["park-sheet"];
    pin(c, "background", "var(--sheet)");
    pin(c, "border", "1px solid var(--gBd)");
    pin(c, "border-radius", "28px");
    pin(c, "box-shadow", "var(--sh)");
    pin(c, "padding", "28px 32px 36px");
  });
});

describe("WEB_2_styles_toast_popover_scrim", () => {
  it("WEB_2_styles_toast_fixed_top92_toast_r16_14_5px_700_shPop", () => {
    const c = ["park-toast"];
    pin(c, "position", "fixed");
    pin(c, "top", "92px");
    pin(c, "background", "var(--toast)");
    pin(c, "color", "var(--toastInk)");
    pin(c, "border-radius", "16px");
    pin(c, "font-size", "14.5px");
    pin(c, "font-weight", "700");
    pin(c, "box-shadow", "var(--shPop)");
  });

  it("WEB_2_styles_toast_inline_is_in_the_flow_for_galleries", () => {
    expect(["static", "relative"]).toContain(val(["park-toast", "park-toast--inline"], "position"));
  });

  it("WEB_2_styles_toast_green_check_dot_24_round_and_action_h32_r10", () => {
    const dot = ["park-toast__dot"];
    pin(dot, "width", "24px");
    pin(dot, "height", "24px");
    pin(dot, "border-radius", "99px");
    pin(dot, "background", "#1E8A4C");
    pin(["park-toast__action"], "height", "32px");
    pin(["park-toast__action"], "border-radius", "10px");
  });

  it("WEB_2_styles_popover_pop_line_r20_shPop_p8", () => {
    const c = ["park-popover"];
    pin(c, "background", "var(--pop)");
    pin(c, "border", "1px solid var(--line)");
    pin(c, "border-radius", "20px");
    pin(c, "box-shadow", "var(--shPop)");
    pin(c, "padding", "8px");
  });

  it("WEB_2_styles_popover_inline_is_in_the_flow_for_galleries", () => {
    expect(["static", "relative"]).toContain(
      val(["park-popover", "park-popover--inline"], "position"),
    );
  });

  it("WEB_2_styles_popover_backdrop_covers_the_viewport", () => {
    const c = ["park-popover__backdrop"];
    pin(c, "position", "fixed");
    const d = declsFor(rules(), c);
    const covers =
      norm(d.get("inset")) === "0" ||
      ["top", "right", "bottom", "left"].every((k) => norm(d.get(k)) === "0");
    expect(covers, "inset: 0 (or top, right, bottom and left all 0)").toBe(true);
  });

  it("WEB_2_styles_menu_row_h42_r12", () => {
    pin(["park-menu__row"], "height", "42px");
    pin(["park-menu__row"], "border-radius", "12px");
  });

  it("WEB_2_styles_scrim_fixed_inset0_scrim_colour", () => {
    const c = ["park-scrim"];
    pin(c, "position", "fixed");
    pin(c, "background", "var(--scrim)");
    const d = declsFor(rules(), c);
    expect(
      norm(d.get("inset")) === "0" ||
        ["top", "right", "bottom", "left"].every((k) => norm(d.get(k)) === "0"),
    ).toBe(true);
  });

  it("WEB_2_styles_scrim_inline_is_contained_for_galleries", () => {
    expect(["relative", "absolute"]).toContain(
      val(["park-scrim", "park-scrim--inline"], "position"),
    );
  });
});
