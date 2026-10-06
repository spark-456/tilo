// WEB-3b: the one stylesheet of the shell, apps/web/src/park/shell/park.shell.css, read with the WEB-2 helpers
// (test-support/park/componentsCss.ts). Convention (same as park.components.css): every selector is
// `[data-park] .class[.class][:pseudo]`, literal values, `var(--token)` colours, NO transition, animation or
// keyframes (the motion restore is BQ-WEB-3). Numbers are the README "Shell" section and the reference
// `Tilo App.dc.html` inline styles. Class names are pinned by the component tests (TopNav.test.tsx, Popovers,
// WorldLoader, Backdrop, AppShell).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { type CssRule, declsFor, norm, parseRules } from "../../../test-support/park/componentsCss";
import { stripComments } from "../../../test-support/park/css";

const FILE = path.join(__dirname, "park.shell.css");
const css = (): string => fs.readFileSync(FILE, "utf8");
const rules = (): CssRule[] => parseRules(css()).rules;
const d = (...classes: string[]) => declsFor(rules(), classes);
// Values compared as the author wrote them (token names keep their case): whitespace collapsed, commas
// tight, hex lower-cased, 0px -> 0 and 0.5 -> .5.
const raw = (m: ReadonlyMap<string, string>, prop: string): string => {
  const names = prop === "background" ? ["background", "background-color"] : [prop];
  for (const n of names) {
    const v = m.get(n);
    if (v !== undefined) {
      return v
        .trim()
        .replace(/\s*!important$/, "")
        .replace(/\s+/g, " ")
        .replace(/\s*,\s*/g, ",")
        .replace(/#([0-9a-fA-F]{3,8})\b/g, (_x, h: string) => `#${h.toLowerCase()}`)
        .replace(/\b0px\b/g, "0")
        .replace(/(^|[^\d])0\.(\d)/g, "$1.$2");
    }
  }
  return "";
};
const px = (...classes: string[]) => (prop: string) => raw(d(...classes), prop);
const inset0 = (...classes: string[]) => {
  const m = d(...classes);
  return raw(m, "inset") === "0" || ["top", "right", "bottom", "left"].every((k) => raw(m, k) === "0");
};

describe("WEB_3b_css: the file follows the stylesheet rules", () => {
  it("WEB_3b_css_every_selector_is_scoped_to_data_park", () => {
    const bad = rules()
      .map((r) => r.selector)
      .filter((s) => !s.startsWith("[data-park]"));
    expect(rules().length).toBeGreaterThan(25);
    expect(bad).toEqual([]);
  });

  it("WEB_3b_css_has_no_transition_animation_or_keyframes", () => {
    const text = stripComments(css());
    expect(text).not.toMatch(/\btransition\b|\banimation\b|@keyframes|animation-play-state/i);
    expect(parseRules(css()).others.map((o) => o.head)).toEqual([]);
  });

  it("WEB_3b_css_has_no_rule_that_depends_on_prefers_reduced_motion_or_will_change", () => {
    expect(stripComments(css())).not.toMatch(/prefers-reduced-motion|will-change/i);
  });
});

describe("WEB_3b_css: the nav", () => {
  it("WEB_3b_css_nav_is_the_fixed_glass_bar_16_14_62_r22", () => {
    const v = px("park-nav");
    expect(v("position")).toBe("fixed");
    expect(v("left")).toBe("16px");
    expect(v("right")).toBe("16px");
    expect(v("top")).toBe("14px");
    expect(v("height")).toBe("62px");
    expect(v("border-radius")).toBe("22px");
    expect(v("background")).toBe("var(--gBg)");
    expect(v("backdrop-filter")).toBe("var(--gFx)");
    expect(v("border")).toBe("1px solid var(--gBd)");
    expect(v("box-shadow")).toBe("var(--sh)");
    expect(v("z-index")).toBe("30");
    expect(v("display")).toBe("flex");
    expect(v("align-items")).toBe("center");
    expect(v("gap")).toBe("16px");
    expect(v("padding")).toBe("0 10px 0 12px");
    expect(v("box-sizing")).toBe("border-box");
  });

  it("WEB_3b_css_logo_tile_is_34_r12_hero_with_a_22x12_r5_white_visor_and_3px_dots", () => {
    expect([px("park-nav__tile")("width"), px("park-nav__tile")("height")]).toEqual(["34px", "34px"]);
    expect(px("park-nav__tile")("border-radius")).toBe("12px");
    expect(px("park-nav__tile")("background")).toBe("var(--hero)");
    const visor = px("park-nav__visor");
    expect([visor("width"), visor("height"), visor("border-radius")]).toEqual(["22px", "12px", "5px"]);
    expect(visor("background")).toBe("#ffffff");
    const eye = px("park-nav__eye");
    expect([eye("width"), eye("height")]).toEqual(["3px", "3px"]);
    expect(eye("background")).toBe("#1f1d2b");
  });

  it("WEB_3b_css_wordmark_is_Nunito_900_27px_minus_half_a_pixel_in_the_logo_colour", () => {
    const w = px("park-nav__word");
    expect(w("font-family")).toMatch(/nunito/i);
    expect(w("font-family")).not.toMatch(/nunito sans/i);
    expect(w("font-weight")).toBe("900");
    expect(w("font-size")).toBe("27px");
    expect(w("letter-spacing")).toBe("-.5px");
    expect(w("color")).toBe("var(--logo)");
  });

  it("WEB_3b_css_tab_strip_scrolls_sideways_and_may_shrink", () => {
    const t = px("park-nav__tabs");
    expect(t("display")).toBe("flex");
    expect(t("gap")).toBe("2px");
    expect(t("flex")).toBe("1");
    expect(t("min-width")).toBe("0");
    expect(t("overflow-x")).toBe("auto");
  });

  it("WEB_3b_css_tab_is_h40_r14_15px_800_and_the_active_tab_uses_heroSoft_heroInk", () => {
    const t = px("park-nav__tab");
    expect(t("height")).toBe("40px");
    expect(t("padding")).toBe("0 14px");
    expect(t("border-radius")).toBe("14px");
    expect(t("font-size")).toBe("15px");
    expect(t("font-weight")).toBe("800");
    expect(t("display")).toBe("flex");
    expect(t("align-items")).toBe("center");
    expect(t("gap")).toBe("7px");
    expect(t("color")).toBe("var(--ink)");
    const on = px("park-nav__tab", "park-nav__tab--on");
    expect(on("background")).toBe("var(--heroSoft)");
    expect(on("color")).toBe("var(--heroInk)");
  });

  it("WEB_3b_css_tab_hover_is_the_chip_background", () => {
    const hover = declsFor(rules(), ["park-nav__tab"], ":hover");
    expect(raw(hover, "background")).toBe("var(--chip)");
  });

  it("WEB_3b_css_badge_is_the_amber_pill_20_high_with_dark_text", () => {
    const b = px("park-nav__badge");
    expect(b("min-width")).toBe("20px");
    expect(b("height")).toBe("20px");
    expect(b("padding")).toBe("0 5px");
    expect(b("border-radius")).toBe("99px");
    expect(b("background")).toBe("#f0a500");
    expect(b("color")).toBe("#1f1d2b");
    expect(b("font-size")).toBe("12px");
    expect(b("font-weight")).toBe("900");
  });

  it("WEB_3b_css_icon_buttons_are_40_r13_and_the_unread_dot_is_a_9px_amber_dot_at_8_9", () => {
    const i = px("park-nav__icon");
    expect([i("width"), i("height"), i("border-radius")]).toEqual(["40px", "40px", "13px"]);
    expect(i("border")).toMatch(/^0\b|none/);
    const u = px("park-nav__unread");
    expect(u("position")).toBe("absolute");
    expect([u("top"), u("right")]).toEqual(["8px", "9px"]);
    expect([u("width"), u("height"), u("border-radius")]).toEqual(["9px", "9px", "99px"]);
    expect(u("background")).toBe("#f0a500");
    expect(u("box-shadow")).toBe("0 0 0 2px var(--pop)");
  });

  it("WEB_3b_css_avatar_is_38_round_with_a_line_ring_and_a_hero_ring_when_marked", () => {
    const a = px("park-nav__avatar");
    expect([a("width"), a("height"), a("border-radius")]).toEqual(["38px", "38px", "999px"]);
    expect(a("margin-left")).toBe("6px");
    expect(a("font-size")).toBe("13px");
    expect(a("font-weight")).toBe("800");
    expect(a("box-shadow")).toBe("0 0 0 2px var(--pop),0 0 0 3.5px var(--line)");
    expect(px("park-nav__avatar", "park-nav__avatar--ring")("box-shadow")).toBe(
      "0 0 0 2px var(--pop),0 0 0 4px var(--hero)",
    );
  });

  it("WEB_3b_css_progress_bar_is_the_3px_hidden_line_along_the_bottom_edge", () => {
    const b = px("park-nav__bar");
    expect(b("position")).toBe("absolute");
    expect([b("left"), b("right"), b("bottom")]).toEqual(["22px", "22px", "-1px"]);
    expect(b("height")).toBe("3px");
    expect(b("border-radius")).toBe("99px");
    expect(b("opacity")).toBe("0");
  });
});

describe("WEB_3b_css: the popovers", () => {
  it("WEB_3b_css_notification_row_is_a_36_tile_a_text_column_and_the_time", () => {
    const r = px("park-notif__row");
    expect(r("display")).toBe("grid");
    expect(r("grid-template-columns")).toBe("36px minmax(0,1fr) auto");
    expect(r("gap")).toBe("12px");
    expect(r("padding")).toBe("10px");
    expect(r("border-radius")).toBe("14px");
    expect(r("border")).toMatch(/^0\b|none/);
    const t = px("park-notif__tile");
    expect([t("width"), t("height"), t("border-radius")]).toEqual(["36px", "36px", "11px"]);
    expect(px("park-notif__title")("font-size")).toBe("14px");
    expect(px("park-notif__title")("font-weight")).toBe("800");
    expect(px("park-notif__sub")("font-size")).toBe("13px");
    expect(px("park-notif__sub")("color")).toBe("var(--ink2)");
    expect(px("park-notif__time")("font-size")).toBe("12.5px");
    expect(px("park-notif__time")("color")).toBe("var(--ink3)");
  });

  it("WEB_3b_css_notification_tiles_are_amber_green_or_red_by_kind", () => {
    expect(px("park-notif__tile--needs")("background")).toBe("var(--amberTile)");
    expect(px("park-notif__tile--needs")("color")).toBe("var(--amberInk)");
    expect(px("park-notif__tile--done")("background")).toBe("var(--okSoft)");
    expect(px("park-notif__tile--done")("color")).toBe("var(--ok)");
    expect(px("park-notif__tile--warn")("background")).toBe("var(--redSoft)");
    expect(px("park-notif__tile--warn")("color")).toBe("var(--red)");
  });

  it("WEB_3b_css_notification_header_is_16px_800_with_a_heroInk_Settings_link", () => {
    expect(px("park-notif__head-title")("font-size")).toBe("16px");
    expect(px("park-notif__head-title")("font-weight")).toBe("800");
    expect(px("park-notif__settings")("color")).toBe("var(--heroInk)");
    expect(px("park-notif__settings")("font-size")).toBe("13.5px");
    expect(px("park-notif__settings")("font-weight")).toBe("800");
  });

  it("WEB_3b_css_account_header_has_a_44_avatar_name_email_org_and_the_separator", () => {
    const h = px("park-acct__head");
    expect(h("display")).toBe("flex");
    expect(h("align-items")).toBe("center");
    expect(h("gap")).toBe("12px");
    expect(h("padding")).toBe("10px 10px 12px");
    const a = px("park-acct__avatar");
    expect([a("width"), a("height"), a("border-radius")]).toEqual(["44px", "44px", "999px"]);
    expect(a("background")).toBe("#e6e1f8");
    expect(a("color")).toBe("#1f1d2b");
    expect([a("font-size"), a("font-weight")]).toEqual(["15px", "800"]);
    expect([px("park-acct__name")("font-size"), px("park-acct__name")("font-weight")]).toEqual(["15px", "800"]);
    expect([px("park-acct__email")("font-size"), px("park-acct__email")("color")]).toEqual(["13px", "var(--ink2)"]);
    expect([px("park-acct__org")("font-size"), px("park-acct__org")("color")]).toEqual(["12.5px", "var(--ink3)"]);
    const s = px("park-acct__sep");
    expect(s("height")).toBe("1px");
    expect(s("background")).toBe("var(--line2)");
    expect(s("margin")).toBe("0 6px 4px");
  });
});

describe("WEB_3b_css: the backdrop and the outlet", () => {
  it("WEB_3b_css_backdrop_is_fixed_full_bleed_behind_everything_and_not_clickable", () => {
    const b = px("park-backdrop");
    expect(b("position")).toBe("fixed");
    expect(inset0("park-backdrop")).toBe(true);
    expect(b("overflow")).toBe("hidden");
    expect(b("background")).toBe("var(--ground)");
    expect(b("z-index")).toBe("0");
    expect(b("pointer-events")).toBe("none");
  });

  it("WEB_3b_css_scene_is_1600x1000_centred_and_the_veil_covers_it", () => {
    const s = px("park-backdrop__scene");
    expect(s("position")).toBe("absolute");
    expect([s("left"), s("top")]).toEqual(["50%", "50%"]);
    expect([s("width"), s("height")]).toEqual(["1600px", "1000px"]);
    expect(s("margin")).toBe("-500px 0 0 -800px");
    expect(s("transform-origin")).toBe("50% 50%");
    const v = px("park-backdrop__veil");
    expect(v("position")).toBe("absolute");
    expect(inset0("park-backdrop__veil")).toBe(true);
    expect(v("background")).toBe("var(--veil)");
  });

  it("WEB_3b_css_content_column_is_1320_centred_with_100_24_56_padding", () => {
    const c = px("park-shell__column");
    expect(c("max-width")).toBe("1320px");
    expect(c("margin")).toBe("0 auto");
    expect(c("padding")).toBe("100px 24px 56px");
    expect(c("box-sizing")).toBe("border-box");
  });

  it("WEB_3b_css_main_sits_above_the_backdrop", () => {
    const m = px("park-shell__main");
    expect(m("position")).toBe("relative");
    expect(m("z-index")).toBe("1");
  });
});

describe("WEB_3b_css: the loader and the boot splash", () => {
  it("WEB_3b_css_loader_scrim_is_fixed_inset_0_z40_centred_on_the_scrim_colour", () => {
    const s = px("park-wl");
    expect(s("position")).toBe("fixed");
    expect(inset0("park-wl")).toBe(true);
    expect(s("z-index")).toBe("40");
    expect(s("display")).toBe("flex");
    expect(s("align-items")).toBe("center");
    expect(s("justify-content")).toBe("center");
    expect(s("background")).toBe("var(--scrim)");
  });

  it("WEB_3b_css_loader_card_is_400_wide_r24_with_the_popup_surface_and_18px_gaps", () => {
    const c = px("park-wl__card");
    expect(c("width")).toBe("400px");
    expect(c("max-width")).toBe("calc(100vw - 48px)");
    expect(c("box-sizing")).toBe("border-box");
    expect(c("background")).toBe("var(--pop)");
    expect(c("border")).toBe("1px solid var(--line)");
    expect(c("border-radius")).toBe("24px");
    expect(c("box-shadow")).toBe("var(--shPop)");
    expect(c("padding")).toBe("22px 24px 24px");
    expect(c("gap")).toBe("18px");
  });

  it("WEB_3b_css_loader_art_eyebrow_name_meta_and_steps", () => {
    const a = px("park-wl__art");
    expect([a("width"), a("height"), a("border-radius")]).toEqual(["58px", "58px", "16px"]);
    expect(a("background")).toBe("var(--sunk)");
    expect(a("align-items")).toBe("flex-end");
    const e = px("park-wl__eyebrow");
    expect([e("font-size"), e("font-weight"), e("letter-spacing")]).toEqual(["12px", "800", ".7px"]);
    expect(e("color")).toBe("var(--ink3)");
    expect([px("park-wl__name")("font-size"), px("park-wl__name")("font-weight")]).toEqual(["19px", "800"]);
    expect([px("park-wl__meta")("font-size"), px("park-wl__meta")("color")]).toEqual(["13.5px", "var(--ink2)"]);
    const st = px("park-wl__step");
    expect([st("font-size"), st("font-weight"), st("gap")]).toEqual(["14px", "700", "10px"]);
  });

  it("WEB_3b_css_loader_states_use_ok_ink_and_ink3_and_the_tick_is_20px", () => {
    const tick = px("park-wl__tick");
    expect([tick("width"), tick("height"), tick("border-radius")]).toEqual(["20px", "20px", "99px"]);
    expect(tick("background")).toBe("var(--track)");
    expect(px("park-wl__tick", "park-wl__tick--done")("background")).toBe("var(--ok)");
    expect(px("park-wl__tick", "park-wl__tick--pending")("background")).toBe("var(--track)");
    expect(px("park-wl__tick", "park-wl__tick--active")("background")).toBe("transparent");
    expect(px("park-wl__step")("color")).toBe("var(--ink)");
    expect(px("park-wl__step", "park-wl__step--pending")("color")).toBe("var(--ink3)");
  });

  it("WEB_3b_css_the_spinner_is_a_static_16px_ring_with_a_hero_top", () => {
    const s = px("park-wl__spin");
    expect([s("width"), s("height")]).toEqual(["16px", "16px"]);
    expect(s("border-radius")).toBe("99px");
    expect(s("border")).toBe("2.5px solid var(--track)");
    expect(s("border-top-color")).toBe("var(--hero)");
    expect(s("box-sizing")).toBe("border-box");
  });

  it("WEB_3b_css_loader_progress_is_a_4px_track_with_a_hero_fill", () => {
    const t = px("park-wl__track");
    expect([t("height"), t("border-radius"), t("overflow")]).toEqual(["4px", "99px", "hidden"]);
    expect(t("background")).toBe("var(--track)");
    expect(px("park-wl__fill")("height")).toBe("100%");
    expect(px("park-wl__fill")("background")).toBe("var(--hero)");
  });

  it("WEB_3b_css_boot_is_a_paper_splash_at_z60", () => {
    const b = px("park-boot");
    expect(b("position")).toBe("fixed");
    expect(inset0("park-boot")).toBe(true);
    expect(b("z-index")).toBe("60");
    expect(b("background")).toBe("var(--paper)");
    expect(b("display")).toBe("flex");
    expect(b("flex-direction")).toBe("column");
    expect(b("align-items")).toBe("center");
    expect(b("justify-content")).toBe("center");
    expect(b("gap")).toBe("22px");
  });

  it("WEB_3b_css_boot_logo_is_56_with_a_36x20_visor_and_a_48px_wordmark", () => {
    const t = px("park-boot__tile");
    expect([t("width"), t("height"), t("border-radius")]).toEqual(["56px", "56px", "18px"]);
    expect(t("background")).toBe("var(--hero)");
    const v = px("park-boot__visor");
    expect([v("width"), v("height"), v("border-radius")]).toEqual(["36px", "20px", "8px"]);
    const w = px("park-boot__word");
    expect([w("font-size"), w("font-weight"), w("letter-spacing")]).toEqual(["48px", "900", "-1.2px"]);
    expect(w("color")).toBe("var(--logo)");
  });

  it("WEB_3b_css_boot_bar_is_a_static_200x4_track_and_the_label_is_14_5px_700", () => {
    const t = px("park-boot__track");
    expect([t("width"), t("height"), t("border-radius")]).toEqual(["200px", "4px", "99px"]);
    expect(t("background")).toBe("var(--track)");
    expect(px("park-boot__fill")("width")).toBe("42%");
    expect(px("park-boot__fill")("background")).toBe("var(--hero)");
    const l = px("park-boot__label");
    expect([l("font-size"), l("font-weight"), l("color")]).toEqual(["14.5px", "700", "var(--ink2)"]);
  });
});

describe("WEB_3b_css: helpers behave", () => {
  it("WEB_3b_css_norm_is_the_helper_the_pins_rely_on", () => {
    expect(norm("0 0 0 2px var(--pop), 0 0 0 3.5px var(--line)")).toBe(
      "0 0 0 2px var(--pop),0 0 0 3.5px var(--line)",
    );
  });
});
