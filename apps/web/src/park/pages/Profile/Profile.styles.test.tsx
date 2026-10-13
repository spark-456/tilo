// @vitest-environment happy-dom
// WEB-12 style pins on the rendered page (design "Tilo App Profile.dc.html" inline styles; README "Shape and
// spacing"): the values come from the reference, read out of its markup. happy-dom loads no CSS, so each
// element's declared style is resolved from Profile.css + park.components.css + inline style with
// test-support/park/pageCss.ts. Rules for the builder, from that helper: a state style (selected tab,
// pressed card, switch on) must be a modifier CLASS on the element (or inline), not an attribute selector
// such as [aria-pressed="true"], which the helper treats as a state and skips; a border or background with
// a var() colour must be a Profile.css rule (happy-dom drops var() from inline shorthands). Real computed
// values at 1440 and 390 are in e2e/park/profile.spec.ts. Hygiene (prefix, motion): Profile.static.test.ts.
// The DOM shapes follow the design's markup (a card's title block is a sibling of its rows; a switch's knob
// is its first child; the matrix header and rows are the grid elements, a row's label and sub sit in one div),
// so the pins find a card, row or tile by walking from its text.
// The 40x24 switch (knob 18, travel 16) is the notification matrix's own; core Switch is 44x26 (knob 20,
// travel 18), which the Quiet hours row keeps. The two-column layout switches at app.vw >= 980 (the design's
// own rule: `wide = vw >= 980`), so it is pinned through the vw prop, not a media query.
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { dv, gaps, rulesOf } from "../../../../test-support/park/pageCss";
import { makeApp } from "../../../../test-support/park/profileApp";
import {
  NOTIF,
  NOTIF_COPY,
  SECURITY_COPY,
  SWATCHES,
  USER,
  switchLabel,
} from "../../../../test-support/park/profileExpect";
import { PARK_DIR } from "../../../../test-support/park/prototype";
import {
  buttonNamed,
  buttonWith,
  cleanup,
  openTab,
  ownText,
  region,
  renderProfile,
  settingsNav,
  switchNamed,
  tabNamed,
  text,
} from "./testApp";

afterEach(cleanup);

const DIR = path.join(PARK_DIR, "pages", "Profile");
const rules = () => rulesOf(path.join(DIR, "Profile.css"));
const d = (el: Element, prop: string): string => dv(el, rules(), prop);
const bg = (el: Element): string => d(el, "background") || d(el, "background-color");
const type = (el: Element): string[] => [d(el, "font-size"), d(el, "font-weight")];
const byText = (root: ParentNode, s: string): Element => {
  const hit = [...root.querySelectorAll("*")].find((e) => ownText(e) === s);
  if (!hit) throw new Error(`no element with text "${s}"`);
  return hit;
};

describe("WEB_12_profile_styles: page sheet and header", () => {
  it("WEB_12_profile_styles_page_sheet_gap_22_padding_28_32_36_radius_28", async () => {
    const { root } = await renderProfile(makeApp());
    const sheet = root.querySelector(".park-sheet") as HTMLElement;
    expect(sheet, "the page is a PageSheet").not.toBeNull();
    expect(sheet.contains(settingsNav(root))).toBe(true);
    expect(gaps(sheet, rules())[0]).toBe(22);
    expect(d(sheet, "padding")).toBe("28px 32px 36px");
    expect(d(sheet, "border-radius")).toBe("28px");
    expect(d(sheet, "box-shadow")).toBe("var(--sh)");
    expect(bg(sheet)).toBe("var(--sheet)");
  });

  it("WEB_12_profile_styles_avatar_72_round_with_the_hero_ring_and_name_type", async () => {
    const { root } = await renderProfile(makeApp());
    const avatar = byText(root, USER.initials);
    expect([d(avatar, "width"), d(avatar, "height"), d(avatar, "border-radius")]).toEqual([
      "72px",
      "72px",
      "999px",
    ]);
    expect([bg(avatar), d(avatar, "color")]).toEqual(["#e6e1f8", "#1f1d2b"]);
    expect(type(avatar)).toEqual(["24px", "800"]);
    expect(d(avatar, "box-shadow")).toBe("0 0 0 3px var(--card),0 0 0 5px var(--hero)");
    const h1 = root.querySelector("h1") as HTMLElement;
    expect([d(h1, "font-size"), d(h1, "font-weight"), d(h1, "letter-spacing")]).toEqual([
      "34px",
      "900",
      "-.8px",
    ]);
    expect(d(h1, "line-height")).toBe("1.05");
    expect(d(h1, "font-family")).toMatch(/^["']?nunito["']?,/);
    const sub = byText(root, `${USER.title} · Northwind Ops · Owner on the Team plan`);
    expect([...type(sub), d(sub, "color")]).toEqual(["15px", "600", "var(--ink2)"]);
  });

  it("WEB_12_profile_styles_connectors_button_h42_r12_secondary", async () => {
    const { root } = await renderProfile(makeApp());
    const b = buttonNamed(root, "Connectors");
    expect([d(b, "height"), d(b, "border-radius"), d(b, "padding")]).toEqual([
      "42px",
      "12px",
      "0 16px 0 14px",
    ]);
    expect(type(b)).toEqual(["14.5px", "800"]);
    expect([bg(b), d(b, "border")]).toEqual(["var(--btn2)", "1px solid var(--line)"]);
    expect(gaps(b, rules())[1]).toBe(8);
  });
});

describe("WEB_12_profile_styles: settings nav and the two layouts", () => {
  it("WEB_12_profile_styles_wide_layout_is_230_plus_fluid_with_a_vertical_nav", async () => {
    const { root } = await renderProfile(makeApp({ vw: 1440 }));
    const nav = settingsNav(root);
    const grid = nav.parentElement as HTMLElement;
    expect(grid.contains(region(root, "Profile"))).toBe(true);
    expect(d(grid, "grid-template-columns")).toBe("230px minmax(0,1fr)");
    expect(gaps(grid, rules())).toEqual([18, 18]);
    expect(d(grid, "align-items")).toBe("start");
    expect(d(nav, "flex-direction")).toBe("column");
  });

  it.each([
    [979, "minmax(0,1fr)", "row"],
    [390, "minmax(0,1fr)", "row"],
    [980, "230px minmax(0,1fr)", "column"],
  ])("WEB_12_profile_styles_vw_%i_gives_columns_%s_and_nav_%s", async (vw, cols, dir) => {
    const { root } = await renderProfile(makeApp({ vw }));
    const nav = settingsNav(root);
    expect(d(nav.parentElement as Element, "grid-template-columns")).toBe(cols);
    expect(d(nav, "flex-direction")).toBe(dir);
  });

  it("WEB_12_profile_styles_nav_card_and_tab_buttons", async () => {
    const { root } = await renderProfile(makeApp());
    const nav = settingsNav(root);
    expect([bg(nav), d(nav, "border"), d(nav, "border-radius"), d(nav, "padding")]).toEqual([
      "var(--card)",
      "1px solid var(--line2)",
      "20px",
      "8px",
    ]);
    expect([d(nav, "overflow-x"), d(nav, "overflow-y"), gaps(nav, rules())[0]]).toEqual([
      "auto",
      "hidden",
      2,
    ]);
    const open = tabNamed(root, "Profile");
    const other = tabNamed(root, "Security");
    for (const t of [open, other]) {
      expect([d(t, "height"), d(t, "padding"), d(t, "border-radius")]).toEqual([
        "42px",
        "0 12px",
        "12px",
      ]);
      expect(type(t)).toEqual(["14.5px", "800"]);
      expect(gaps(t, rules())[1]).toBe(10);
      expect(d(t, "flex")).toMatch(/^(none|0 0 auto)$/);
    }
    expect([bg(open), d(open, "color")]).toEqual(["var(--rowon)", "var(--heroink)"]);
    expect([bg(other), d(other, "color")]).toEqual(["transparent", "var(--ink)"]);
  });
});

describe("WEB_12_profile_styles: section cards", () => {
  it.each([
    ["Profile", "22px 24px", 18],
    ["Notifications", "22px 24px 12px", 6],
    ["Appearance", "22px 24px", 22],
    ["Security", "22px 24px 12px", 6],
  ])("WEB_12_profile_styles_%s_card_padding_%s_gap_%i_radius_22", async (name, padding, gap) => {
    const { root } = await renderProfile(makeApp());
    if (name !== "Profile") await openTab(root, name);
    const card = region(root, name);
    expect(d(card, "padding"), name).toBe(padding);
    expect(gaps(card, rules())[0], name).toBe(gap);
    expect(d(card, "border-radius"), name).toBe("22px");
    expect(d(card, "border"), name).toBe("1px solid var(--line2)");
    expect(bg(card), name).toBe("var(--card)");
  });

  it("WEB_12_profile_styles_card_title_and_sub_type", async () => {
    const { root } = await renderProfile(makeApp());
    const h2 = region(root, "Profile").querySelector("h2") as Element;
    expect(type(h2)).toEqual(["18px", "800"]);
    const sub = byText(root, "How you appear to your team and how Tilo addresses you.");
    expect([...type(sub), d(sub, "color")]).toEqual(["13.5px", "600", "var(--ink2)"]);
  });
});

describe("WEB_12_profile_styles: profile form", () => {
  it("WEB_12_profile_styles_field_label_input_help_and_grid", async () => {
    const { root } = await renderProfile(makeApp());
    const label = byText(root, "Full name");
    expect([...type(label), d(label, "color")]).toEqual(["13px", "800", "var(--ink2)"]);
    const input = root.querySelector("input") as HTMLInputElement;
    expect([d(input, "height"), d(input, "border-radius"), d(input, "padding")]).toEqual([
      "44px",
      "12px",
      "0 14px",
    ]);
    expect([...type(input), bg(input), d(input, "border")]).toEqual([
      "15px",
      "700",
      "var(--field)",
      "1px solid var(--line)",
    ]);
    const help = byText(root, "Shown to your team");
    expect([...type(help), d(help, "color")]).toEqual(["12.5px", "600", "var(--ink3)"]);
    const grid = input.closest("label")?.parentElement as Element;
    expect(d(grid, "grid-template-columns")).toBe("repeat(auto-fit,minmax(240px,1fr))");
    expect(gaps(grid, rules())).toEqual([14, 14]);
  });

  it("WEB_12_profile_styles_cancel_and_save_buttons_h40_r12_and_the_footer_rule", async () => {
    const { root } = await renderProfile(makeApp());
    const cancel = buttonNamed(root, "Cancel");
    const save = buttonNamed(root, "Save changes");
    for (const b of [cancel, save]) {
      expect([d(b, "height"), d(b, "border-radius"), ...type(b)]).toEqual([
        "40px",
        "12px",
        "14px",
        "800",
      ]);
    }
    expect(d(cancel, "padding")).toBe("0 16px");
    expect(d(save, "padding")).toBe("0 18px");
    expect([bg(cancel), d(cancel, "border")]).toEqual(["var(--btn2)", "1px solid var(--line)"]);
    expect(bg(save)).toBe("var(--herofill)"); // BQ-DS-A11Y-1: the computed value is lower-cased
    const footer = save.parentElement as Element;
    expect([d(footer, "justify-content"), gaps(footer, rules())[1]]).toEqual(["flex-end", 8]);
    expect(d(footer, "border-top")).toBe("1px solid var(--line2)");
  });
});

describe("WEB_12_profile_styles: notification matrix", () => {
  it("WEB_12_profile_styles_matrix_header_and_rows_use_the_design_grid", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    const head = byText(root, "WHEN").parentElement as Element;
    const COLS = "minmax(0,1fr) repeat(3,92px)";
    expect(d(head, "grid-template-columns")).toBe(COLS);
    expect(d(head, "height")).toBe("32px");
    expect([...type(head), d(head, "letter-spacing"), d(head, "color")]).toEqual([
      "12px",
      "800",
      ".5px",
      "var(--ink3)",
    ]);
    const first = byText(root, NOTIF[0]?.[1] ?? "").parentElement?.parentElement as Element;
    expect(d(first, "grid-template-columns")).toBe(COLS);
    expect(d(first, "min-height")).toBe("58px");
    expect(d(first, "border-top")).toBe("1px solid var(--line2)");
    const label = byText(root, NOTIF[0]?.[1] ?? "");
    const sub = byText(root, NOTIF[0]?.[2] ?? "");
    expect(type(label)).toEqual(["14.5px", "800"]);
    expect([...type(sub), d(sub, "color")]).toEqual(["13px", "600", "var(--ink2)"]);
    const scroller = head.parentElement?.parentElement as Element;
    expect([d(head.parentElement as Element, "min-width"), d(scroller, "overflow-x")]).toEqual([
      "520px",
      "auto",
    ]);
  });

  it("WEB_12_profile_styles_matrix_switches_are_40_by_24_knob_18_travel_16", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    const on = switchNamed(root, switchLabel("A decision needs you", "Phone"));
    const off = switchNamed(root, switchLabel("Spend goes over a limit", "Slack"));
    expect(on.getAttribute("aria-checked")).toBe("true");
    expect(off.getAttribute("aria-checked")).toBe("false");
    for (const sw of [on, off]) {
      expect([d(sw, "width"), d(sw, "height"), d(sw, "border-radius"), d(sw, "padding")]).toEqual([
        "40px",
        "24px",
        "99px",
        "3px",
      ]);
      const knob = sw.firstElementChild as Element;
      expect([d(knob, "width"), d(knob, "height"), d(knob, "border-radius")]).toEqual([
        "18px",
        "18px",
        "99px",
      ]);
      expect(d(knob, "box-shadow")).toBe("0 1px 3px rgba(31,29,43,.3)");
    }
    expect(bg(on)).toBe("var(--ok)");
    expect(bg(off)).toBe("var(--track)");
    expect(d(on.firstElementChild as Element, "transform")).toBe("translatex(16px)");
    expect(["", "none"]).toContain(d(off.firstElementChild as Element, "transform"));
  });

  it("WEB_12_profile_styles_quiet_hours_row_and_its_44_by_26_switch", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    const quiet = switchNamed(root, NOTIF_COPY.quietLabel);
    expect([d(quiet, "width"), d(quiet, "height"), d(quiet, "padding")]).toEqual([
      "44px",
      "26px",
      "3px",
    ]);
    const knob = quiet.firstElementChild as Element;
    expect([d(knob, "width"), d(knob, "height")]).toEqual(["20px", "20px"]);
    expect(d(knob, "transform")).toBe("translatex(18px)");
    const row = quiet.parentElement as Element;
    expect([bg(row), d(row, "border-radius"), d(row, "padding"), d(row, "margin-top")]).toEqual([
      "var(--sunk)",
      "16px",
      "14px 16px",
      "6px",
    ]);
    expect(gaps(row, rules())[1]).toBe(14);
    const tile = row.querySelector("svg")?.parentElement as Element;
    expect([d(tile, "width"), d(tile, "height"), d(tile, "border-radius")]).toEqual([
      "36px",
      "36px",
      "11px",
    ]);
    expect([bg(tile), d(tile, "color")]).toEqual(["var(--herosoft)", "var(--heroink)"]);
    expect(type(byText(root, NOTIF_COPY.quiet))).toEqual(["14.5px", "800"]);
  });
});

describe("WEB_12_profile_styles: appearance", () => {
  it("WEB_12_profile_styles_time_cards_border_swatch_and_blocks", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Appearance");
    const day = buttonWith(root, "Bright lawns");
    const night = buttonWith(root, "Lamps and glow");
    const grid = day.parentElement as Element;
    expect(d(grid, "grid-template-columns")).toBe("repeat(auto-fit,minmax(180px,1fr))");
    expect(gaps(grid, rules())).toEqual([12, 12]);
    for (const c of [day, night]) {
      expect([d(c, "padding"), d(c, "border-radius"), bg(c)]).toEqual([
        "10px",
        "18px",
        "var(--card)",
      ]);
      expect(gaps(c, rules())[0]).toBe(10);
    }
    expect(d(day, "border"), "selected").toBe("2px solid var(--hero)");
    expect(d(night, "border"), "not selected").toBe("2px solid var(--line)");
    const swatch = day.firstElementChild as Element;
    expect([d(swatch, "height"), d(swatch, "border-radius"), d(swatch, "padding")]).toEqual([
      "84px",
      "12px",
      "10px",
    ]);
    expect(gaps(swatch, rules())[1]).toBe(6);
    const sizes = [...swatch.children].map((b) => [
      d(b, "width"),
      d(b, "height"),
      d(b, "border-radius"),
    ]);
    expect(sizes).toEqual([
      ["44px", "30px", "7px"],
      ["30px", "46px", "7px"],
      ["38px", "22px", "7px"],
    ]);
    expect(type(byText(day, "Day"))).toEqual(["14.5px", "800"]);
    const sub = byText(day, "Bright lawns");
    expect([...type(sub), d(sub, "color")]).toEqual(["12.5px", "700", "var(--ink3)"]);
  });

  it("WEB_12_profile_styles_swatch_colours_are_the_designs_day_and_night", () => {
    // UI-10 W8 moved the controls into AppearanceControls; keep the exact swatch assertions.
    const src = ["ProfilePage.tsx", "AppearanceControls.tsx", "Profile.css"]
      .map((f) => {
        try {
          return readFileSync(path.join(DIR, f), "utf8");
        } catch {
          return "";
        }
      })
      .join("\n")
      .toLowerCase();
    for (const hex of [...SWATCHES.day, ...SWATCHES.night]) {
      expect(src, hex).toContain(hex.toLowerCase());
    }
  });

  it("WEB_12_profile_styles_motion_control_track_and_items", async () => {
    const { root } = await renderProfile(makeApp({ motion: "calm" }));
    await openTab(root, "Appearance");
    const calm = buttonNamed(root, "Calm");
    const lively = buttonNamed(root, "Lively");
    const track = calm.parentElement as Element;
    expect([bg(track), d(track, "padding"), d(track, "border-radius")]).toEqual([
      "var(--seg)",
      "3px",
      "12px",
    ]);
    expect(gaps(track, rules())[1]).toBe(2);
    expect(d(track, "align-self")).toBe("flex-start");
    for (const b of [calm, lively]) {
      expect([d(b, "height"), d(b, "padding"), d(b, "border-radius"), ...type(b)]).toEqual([
        "36px",
        "0 16px",
        "9px",
        "14px",
        "800",
      ]);
    }
    expect([bg(calm), d(calm, "color"), d(calm, "box-shadow")]).toEqual([
      "var(--tabon)",
      "var(--ink)",
      "0 1px 3px rgba(31,29,43,.16)",
    ]);
    expect([bg(lively), d(lively, "color")]).toEqual(["transparent", "var(--ink2)"]);
  });
});

describe("WEB_12_profile_styles: security", () => {
  it("WEB_12_profile_styles_security_rows_tiles_and_buttons", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Security");
    const title = byText(root, SECURITY_COPY.rows[0][0]);
    expect(type(title)).toEqual(["14.5px", "800"]);
    const row = title.parentElement?.parentElement as Element;
    expect([d(row, "padding"), d(row, "border-top")]).toEqual(["12px 0", "1px solid var(--line2)"]);
    expect(gaps(row, rules())[1]).toBe(14);
    const tile = row.querySelector("svg")?.parentElement as Element;
    expect([d(tile, "width"), d(tile, "height"), d(tile, "border-radius")]).toEqual([
      "38px",
      "38px",
      "11px",
    ]);
    expect([bg(tile), d(tile, "color")]).toEqual(["var(--oksoft)", "var(--ok)"]);
    const manage = buttonNamed(root, "Manage");
    expect([d(manage, "height"), d(manage, "padding"), d(manage, "border-radius")]).toEqual([
      "36px",
      "0 14px",
      "10px",
    ]);
    expect(type(manage)).toEqual(["13.5px", "800"]);
    const all = buttonNamed(root, SECURITY_COPY.everywhere);
    expect([d(all, "color"), d(all, "padding"), ...type(all)]).toEqual([
      "var(--redink)",
      "4px 6px",
      "13.5px",
      "800",
    ]);
    expect(type(byText(root, SECURITY_COPY.signedIn))).toEqual(["15px", "800"]);
  });

  it("WEB_12_profile_styles_session_chip_and_sign_out_buttons", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Security");
    const chip = byText(root, SECURITY_COPY.thisDevice);
    expect([d(chip, "height"), d(chip, "padding"), d(chip, "border-radius")]).toEqual([
      "24px",
      "0 9px",
      "7px",
    ]);
    expect([bg(chip), d(chip, "color"), ...type(chip)]).toEqual([
      "var(--oksoft)",
      "var(--okink)",
      "12px",
      "800",
    ]);
    const out = [...root.querySelectorAll("button")].find(
      (b) => text(b) === SECURITY_COPY.signOut,
    ) as Element;
    expect([d(out, "height"), d(out, "padding"), d(out, "border-radius"), ...type(out)]).toEqual([
      "34px",
      "0 12px",
      "10px",
      "13px",
      "800",
    ]);
    const row = chip.parentElement as Element;
    expect([d(row, "padding"), d(row, "border-top")]).toEqual(["10px 0", "1px solid var(--line2)"]);
    const tile = row.querySelector("svg")?.parentElement as Element;
    expect([bg(tile), d(tile, "color")]).toEqual(["var(--sunk)", "var(--ink2)"]);
  });
});

describe("WEB_12_profile_styles: plan and billing", () => {
  it("WEB_12_profile_styles_billing_cards_labels_and_spend_bar", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Plan and billing");
    const section = region(root, "Plan and billing");
    expect(gaps(section, rules())[0]).toBe(18);
    expect(bg(section), "the section itself is not a card").not.toBe("var(--card)");
    const plan = byText(root, "PLAN").parentElement as Element;
    expect([
      d(plan, "padding"),
      d(plan, "border-radius"),
      bg(plan),
      gaps(plan, rules())[0],
    ]).toEqual(["20px 22px", "22px", "var(--card)", 10]);
    const grid = plan.parentElement as Element;
    expect(d(grid, "grid-template-columns")).toBe("repeat(auto-fit,minmax(260px,1fr))");
    expect(gaps(grid, rules())).toEqual([18, 18]);
    const label = byText(root, "PLAN");
    expect([...type(label), d(label, "letter-spacing"), d(label, "color")]).toEqual([
      "12px",
      "800",
      ".6px",
      "var(--ink3)",
    ]);
    const name = byText(root, "Team");
    expect([...type(name), d(name, "letter-spacing")]).toEqual(["24px", "800", "-.4px"]);
    const ledger = buttonWith(root, "Open the Ledger");
    expect([d(ledger, "padding"), d(ledger, "border-radius"), d(ledger, "text-align")]).toEqual([
      "20px 22px",
      "22px",
      "left",
    ]);
    const fill = [...ledger.querySelectorAll<HTMLElement>("[style]")].find(
      (e) => e.style.width,
    ) as Element;
    expect(bg(fill)).toBe("var(--hero)");
    const track = fill.parentElement as Element;
    expect([d(track, "height"), d(track, "border-radius"), bg(track)]).toEqual([
      "6px",
      "99px",
      "var(--track)",
    ]);
    expect(d(byText(root, "Open the Ledger"), "color")).toBe("var(--heroink)");
  });

  it("WEB_12_profile_styles_invoices_card_and_rows", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Plan and billing");
    const h2 = byText(root, "Invoices");
    expect(type(h2)).toEqual(["17px", "800"]);
    const card = h2.parentElement as Element;
    expect([d(card, "padding"), d(card, "border-radius"), bg(card)]).toEqual([
      "18px 22px 8px",
      "22px",
      "var(--card)",
    ]);
    const row = byText(root, "September 2026 · 5 seats").parentElement as Element;
    expect(d(row, "grid-template-columns")).toBe("minmax(0,1fr) 110px 90px 40px");
    expect([gaps(row, rules())[1], d(row, "min-height"), d(row, "border-top")]).toEqual([
      12,
      "50px",
      "1px solid var(--line2)",
    ]);
    const download = row.querySelector('button[aria-label="Download"]') as Element;
    expect([d(download, "width"), d(download, "height"), d(download, "border-radius")]).toEqual([
      "34px",
      "34px",
      "10px",
    ]);
  });
});
