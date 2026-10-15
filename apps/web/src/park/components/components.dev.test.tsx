// @vitest-environment happy-dom
// WEB-2 /dev/components (PROMPTS step 2: "a page that shows each one in day and night"). The page is the
// named export `Components` of src/park/dev/Components.tsx. It holds two `data-park` panels, day and night,
// each with the same demos, tagged `data-demo="<id>"`. UX-1: exactly one filled primary Button per panel.
// Registered at /dev/components in the dev build only (the static test pins the routes.tsx shape).
import { afterEach, describe, expect, it } from "vitest";
import {
  active,
  cleanup,
  click,
  countPrimary,
  focus,
  mount,
  nameOf,
  pressDocument,
  q,
  qa,
} from "../../../test-support/park/componentsHarness";
import { Components } from "../dev/Components";

afterEach(cleanup);

const DEMOS = [
  "button-primary",
  "button-secondary",
  "button-needs",
  "seg-plain",
  "seg-sliding",
  "seg-sliding-lg",
  "seg-sliding-3",
  "switch",
  "chip",
  "pill",
  "kpi",
  "list-row",
  "art-tile",
  "card",
  "page-sheet",
  "toast",
  "menu-static",
  "menu-live",
  "scrim",
  // UI-STUDIO-1: the theme switch and the shared states
  "theme-switch",
  "state-empty",
  "state-loading",
  "state-error",
] as const;

const PANELS = [
  ["day", "panel-day"],
  ["night", "panel-night"],
] as const;

const classes = (el: Element) => [...el.classList];

describe("WEB_2_dev_page: two data-park panels, day and night", () => {
  it("WEB_2_dev_page_has_a_root_and_exactly_two_data_park_panels", () => {
    const { container } = mount(<Components />);
    expect(container.querySelector('[data-testid="dev-components"]')).not.toBeNull();
    expect(qa(container, "[data-park]")).toHaveLength(2);
    for (const [time, id] of PANELS) {
      const panel = q(container, `[data-testid="${id}"]`);
      expect(panel.hasAttribute("data-park")).toBe(true);
      expect(panel.getAttribute("data-time")).toBe(time);
    }
  });

  it("WEB_2_dev_page_each_panel_is_headed_Day_or_Night", () => {
    const { container } = mount(<Components />);
    const [day, night] = PANELS.map(([, id]) => q(container, `[data-testid="${id}"]`));
    expect(q(day as Element, "h2").textContent).toBe("Day");
    expect(q(night as Element, "h2").textContent).toBe("Night");
  });

  it.each(PANELS)("WEB_2_dev_page_%s_panel_shows_every_demo_exactly_once", (_t, id) => {
    const { container } = mount(<Components />);
    const panel = q(container, `[data-testid="${id}"]`);
    const found = qa(panel, "[data-demo]").map((d) => d.getAttribute("data-demo"));
    expect([...found].sort()).toEqual([...DEMOS].sort());
  });

  it("WEB_2_dev_page_day_and_night_show_the_same_demos", () => {
    const { container } = mount(<Components />);
    const ids = PANELS.map(([, id]) =>
      qa(q(container, `[data-testid="${id}"]`), "[data-demo]").map((d) =>
        d.getAttribute("data-demo"),
      ),
    );
    expect(ids[0]).toEqual(ids[1]);
  });

  it.each(PANELS)("WEB_2_dev_page_UX_1_%s_panel_has_exactly_one_primary_button", (_t, id) => {
    const { container } = mount(<Components />);
    const panel = q(container, `[data-testid="${id}"]`);
    expect(countPrimary(panel)).toBe(1);
    expect(qa(q(panel, '[data-demo="button-primary"]'), "button.park-btn--primary")).toHaveLength(
      1,
    );
  });

  it("WEB_2_dev_page_motion_free_no_transition_or_animation_in_the_markup", () => {
    const { container } = mount(<Components />);
    expect(container.innerHTML).not.toMatch(/transition|animation|@keyframes/i);
  });
});

describe("WEB_2_dev_page: every variant is on show", () => {
  const panel = () => q(mount(<Components />).container, '[data-testid="panel-day"]');
  const demo = (p: HTMLElement, id: string) => q(p, `[data-demo="${id}"]`);

  it("WEB_2_dev_page_secondary_shows_a_disabled_button_and_a_small_one", () => {
    const d = demo(panel(), "button-secondary");
    const btns = qa<HTMLButtonElement>(d, "button");
    expect(btns.some((b) => b.disabled)).toBe(true);
    expect(btns.some((b) => classes(b).includes("park-btn--sm"))).toBe(true);
    expect(btns.every((b) => classes(b).includes("park-btn--secondary"))).toBe(true);
  });

  it("WEB_2_dev_page_needs_demo_is_all_needs_buttons", () => {
    const btns = qa(demo(panel(), "button-needs"), "button");
    expect(btns.length).toBeGreaterThanOrEqual(1);
    expect(btns.every((b) => classes(b).includes("park-btn--needs"))).toBe(true);
  });

  it("WEB_2_dev_page_a_leading_icon_button_is_shown_but_the_one_primary_has_no_icon", () => {
    const p = panel();
    expect(qa(p, "button.park-btn--icon").length).toBeGreaterThanOrEqual(1);
    // e2e pins the primary's padding at 0 18px, the no-icon value; the icon padding (14px) is in the CSS spec.
    expect(classes(q(p, "button.park-btn--primary"))).not.toContain("park-btn--icon");
  });

  it("WEB_2_dev_page_segmented_plain_has_no_thumb_and_sliding_has_one", () => {
    const p = panel();
    expect(demo(p, "seg-plain").querySelector(".park-seg__thumb")).toBeNull();
    expect(demo(p, "seg-sliding").querySelector(".park-seg__thumb")).not.toBeNull();
  });

  it("WEB_2_dev_page_the_demos_are_live_clicking_a_segment_selects_it", () => {
    const p = panel();
    const items = qa(demo(p, "seg-sliding"), '[role="radio"], [role="tab"]');
    const sel = () =>
      qa(demo(p, "seg-sliding"), '[role="radio"], [role="tab"]').filter(
        (i) =>
          i.getAttribute("aria-checked") === "true" || i.getAttribute("aria-selected") === "true",
      );
    const before = sel()[0];
    const other = items.find((i) => i !== before) as HTMLElement;
    click(other);
    expect(sel()).toHaveLength(1);
    expect(sel()[0]).toBe(other);
  });

  it("WEB_2_dev_page_sliding_demos_are_N4_N2_lg_and_N3", () => {
    const p = panel();
    const items = (id: string) => qa(demo(p, id), '[role="radio"], [role="tab"]');
    expect(items("seg-sliding")).toHaveLength(4);
    expect(items("seg-sliding-lg")).toHaveLength(2);
    expect(items("seg-sliding-3")).toHaveLength(3);
    for (const id of ["seg-sliding", "seg-sliding-lg", "seg-sliding-3"])
      expect(demo(p, id).querySelector(".park-seg__thumb"), id).not.toBeNull();
    for (const it of items("seg-sliding-lg")) expect(classes(it)).toContain("park-seg__item--lg");
    for (const it of items("seg-sliding")) expect(classes(it)).not.toContain("park-seg__item--lg");
  });

  it("WEB_2_dev_page_the_tools_demo_labels_and_tones_are_Off_ink2_Read_sch_Draft_heroInk_Act_amberInk", () => {
    const p = panel();
    const items = () => qa(demo(p, "seg-sliding"), '[role="radio"], [role="tab"]');
    expect(items().map((i) => i.textContent)).toEqual(["Off", "Read", "Draft", "Act"]);
    const want = ["ink2", "sch", "heroInk", "amberInk"];
    for (let i = 0; i < 4; i++) {
      click(items()[i] as HTMLElement);
      expect(classes(items()[i] as Element), `selected ${i}`).toContain(
        `park-seg__item--${want[i]}`,
      );
    }
  });

  it("WEB_2_dev_page_the_board_style_demo_is_a_two_option_lg_toggle", () => {
    const items = qa(demo(panel(), "seg-sliding-lg"), '[role="radio"], [role="tab"]');
    expect(items.map((i) => i.textContent)).toEqual(["Pinboard", "Grouped"]);
  });

  it("WEB_2_dev_page_a_list_row_trail_is_a_small_chip_over_a_cost_line", () => {
    const trails = qa(demo(panel(), "list-row"), ".park-row__trail").filter((t) =>
      t.querySelector(".park-chip--sm"),
    );
    expect(trails.length).toBeGreaterThanOrEqual(1);
    for (const t of trails) {
      const kids = [...t.children];
      expect(kids).toHaveLength(2);
      expect(classes(kids[0] as Element)).toContain("park-chip--sm");
      expect(classes(kids[1] as Element)).toContain("park-row__cost");
      expect(kids[1]?.textContent?.length).toBeGreaterThan(0);
    }
  });

  it("WEB_2_dev_page_switches_show_both_states_and_toggle", () => {
    const p = panel();
    const sws = qa(demo(p, "switch"), '[role="switch"]');
    const states = sws.map((s) => s.getAttribute("aria-checked"));
    expect(states).toContain("true");
    expect(states).toContain("false");
    const off = sws.find((s) => s.getAttribute("aria-checked") === "false") as HTMLElement;
    click(off);
    expect(off.getAttribute("aria-checked")).toBe("true");
  });

  it("WEB_2_dev_page_chips_and_pills_show_all_four_tones", () => {
    const p = panel();
    for (const [id, base] of [
      ["chip", "park-chip"],
      ["pill", "park-pill"],
    ] as const) {
      const tones = qa(demo(p, id), `.${base}`).flatMap((c) =>
        classes(c).filter((k) => k.startsWith(`${base}--`) && k !== `${base}--sm`),
      );
      expect([...new Set(tones)].sort()).toEqual(
        ["ok", "hero", "amber", "neutral"].map((t) => `${base}--${t}`).sort(),
      );
    }
  });

  it("WEB_2_dev_page_kpi_tiles_show_default_amber_ok_and_sch", () => {
    const tiles = qa(demo(panel(), "kpi"), ".park-kpi");
    expect(tiles.length).toBeGreaterThanOrEqual(4);
    const all = tiles.flatMap(classes);
    expect(all).toContain("park-kpi--amber");
    expect(all).toContain("park-kpi--ok");
    expect(all, "the Ledger's 'Saved by memory' tint").toContain("park-kpi--sch");
    expect(tiles.some((t) => !classes(t).some((k) => k.startsWith("park-kpi--")))).toBe(true);
  });

  it("WEB_2_dev_page_list_rows_show_resting_selected_and_actionable", () => {
    const rows = qa(demo(panel(), "list-row"), ".park-row");
    expect(rows.length).toBeGreaterThanOrEqual(3);
    expect(rows.some((r) => classes(r).includes("park-row--on"))).toBe(true);
    expect(rows.some((r) => classes(r).includes("park-row--action"))).toBe(true);
    expect(
      rows.some(
        (r) => classes(r).includes("park-row--action") && !classes(r).includes("park-row--on"),
      ),
      "an actionable row that is not selected (the hover check needs one)",
    ).toBe(true);
  });

  it("WEB_2_dev_page_art_tiles_show_at_least_two_tints_with_art_inside", () => {
    const tiles = qa(demo(panel(), "art-tile"), ".park-art");
    expect(tiles.length).toBeGreaterThanOrEqual(2);
    const tints = new Set(
      tiles.flatMap((t) => classes(t).filter((k) => k.startsWith("park-art--"))),
    );
    expect(tints.size).toBeGreaterThanOrEqual(2);
    for (const t of tiles) expect(t.querySelector("svg, img")).not.toBeNull();
  });

  it("WEB_2_dev_page_card_and_page_sheet_each_hold_content", () => {
    const p = panel();
    expect(demo(p, "card").querySelector(".park-card")?.textContent?.length).toBeGreaterThan(0);
    expect(demo(p, "page-sheet").querySelector(".park-sheet")?.textContent?.length).toBeGreaterThan(
      0,
    );
  });

  it("WEB_2_dev_page_toast_demo_is_inline_with_an_action", () => {
    const toast = q(demo(panel(), "toast"), ".park-toast");
    expect(classes(toast)).toContain("park-toast--inline");
    expect(toast.querySelector("button.park-toast__action")).not.toBeNull();
  });

  it("WEB_2_dev_page_static_menu_is_an_inline_menu_of_menuitems_and_has_no_backdrop", () => {
    const d = demo(panel(), "menu-static");
    const menu = q(d, '[role="menu"]');
    expect(classes(menu)).toContain("park-popover--inline");
    expect(qa(menu, '[role="menuitem"]').length).toBeGreaterThanOrEqual(3);
    expect(d.querySelector(".park-popover__backdrop")).toBeNull();
  });

  it("WEB_2_dev_page_scrim_demo_is_an_inline_scrim", () => {
    const s = q(demo(panel(), "scrim"), ".park-scrim");
    expect(classes(s)).toContain("park-scrim--inline");
  });
});

describe("WEB_2_dev_page: the live menu opens, closes on Escape and gives focus back", () => {
  it.each(PANELS)("WEB_2_dev_page_%s_live_menu_escape_closes_and_returns_focus", (_t, id) => {
    const { container } = mount(<Components />);
    const d = q(container, `[data-testid="${id}"] [data-demo="menu-live"]`);
    const trigger = q<HTMLButtonElement>(d, 'button[aria-haspopup="menu"]');
    expect(d.querySelector('[role="menu"]')).toBeNull();
    expect(trigger.getAttribute("aria-expanded")).not.toBe("true");
    focus(trigger);
    click(trigger);
    expect(d.querySelector('[role="menu"]')).not.toBeNull();
    expect(nameOf(active() as Element).length).toBeGreaterThan(0);
    pressDocument("Escape");
    expect(d.querySelector('[role="menu"]')).toBeNull();
    expect(active()).toBe(trigger);
  });

  it("WEB_2_dev_page_live_menu_backdrop_click_closes_it", () => {
    const { container } = mount(<Components />);
    const d = q(container, '[data-testid="panel-day"] [data-demo="menu-live"]');
    const trigger = q(d, 'button[aria-haspopup="menu"]');
    focus(trigger);
    click(trigger);
    click(q(d, ".park-popover__backdrop"));
    expect(d.querySelector('[role="menu"]')).toBeNull();
  });
});
