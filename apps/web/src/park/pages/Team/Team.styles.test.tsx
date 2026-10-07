// @vitest-environment happy-dom
// WEB-10 style pins on the rendered page (design "Tilo App Team.dc.html" inline styles; README "Shape and
// spacing"): the values come from the reference, read out of its markup. happy-dom loads no CSS, so each
// element's declared style is resolved from Team.css + park.components.css + inline style with
// test-support/park/pageCss.ts (class-based or inline both pass, except that a border or background with a
// var() colour must be a Team.css rule: happy-dom drops var() from inline shorthands). Real computed values at
// 1440 and 390 are in e2e/park/team.spec.ts. Stylesheet hygiene (prefix, motion): Team.static.test.ts.
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { dv, gaps, rulesOf } from "../../../../test-support/park/pageCss";
import { PARK_DIR } from "../../../../test-support/park/prototype";
import { COPY, COVERAGE, MATRIX, PEOPLE } from "../../../../test-support/park/teamExpect";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import { inputNamed, ownText, region, rowsOf, typeInto } from "./testApp";

afterEach(cleanup);

const TEAM_CSS = path.join(PARK_DIR, "pages", "Team", "Team.css");
const rules = () => rulesOf(TEAM_CSS);
const d = (el: Element, prop: string): string => dv(el, rules(), prop);
const bg = (el: Element): string => d(el, "background") || d(el, "background-color");
const kids = (el: Element): HTMLElement[] => [...el.children] as HTMLElement[];
const text = (el: Element | null | undefined): string => (el?.textContent ?? "").trim();

const MEMBERS_COLS = "minmax(0,1.6fr) 150px 110px 110px 100px 44px";
const COVER_COLS = "minmax(0,1.3fr) minmax(0,1fr) 110px minmax(150px,auto)";
const MATRIX_COLS = "minmax(0,1fr) repeat(4,72px)";

describe("WEB_10_team_styles: page sheet and cards", () => {
  it("WEB_10_team_styles_page_sheet_gap_22_padding_28_32_36_radius_28", async () => {
    const { root } = await renderTeam(makeApp());
    const sheet = root.querySelector(".park-sheet") as HTMLElement;
    expect(sheet, "the page is a PageSheet").not.toBeNull();
    expect(sheet.contains(region(root, "Members"))).toBe(true);
    expect(gaps(sheet, rules())[0]).toBe(22);
    expect(d(sheet, "padding")).toBe("28px 32px 36px");
    expect(d(sheet, "border-radius")).toBe("28px");
    expect(d(sheet, "box-shadow")).toBe("var(--sh)");
    expect(bg(sheet)).toBe("var(--sheet)");
  });

  it.each([
    ["Members", "14px 18px 6px"],
    ["Approval coverage", "18px 20px 8px"],
    ["Approval rules", "18px 20px 8px"],
    ["What each role can do", "18px 20px 12px"],
  ])(
    "WEB_10_team_styles_%s_card_padding_%s_radius_22_on_the_card_surface",
    async (name, padding) => {
      const { root } = await renderTeam(makeApp());
      const card = region(root, name);
      expect(d(card, "padding"), name).toBe(padding);
      expect(d(card, "border-radius"), name).toBe("22px");
      expect(d(card, "border"), name).toBe("1px solid var(--line2)");
      expect(bg(card), name).toBe("var(--card)");
    },
  );

  it("WEB_10_team_styles_title_count_and_intro_type", async () => {
    const { root } = await renderTeam(makeApp());
    const h1 = root.querySelector("h1") as HTMLElement;
    expect(d(h1, "font-size")).toBe("36px");
    expect(d(h1, "font-weight")).toBe("900");
    expect(d(h1, "letter-spacing")).toBe("-.8px");
    expect(d(h1, "line-height")).toBe("1.05");
    expect(d(h1, "font-family")).toMatch(/^["']?nunito["']?,/);
    const count = [...root.querySelectorAll("*")].find((e) => ownText(e) === COPY.count) as Element;
    expect([d(count, "font-size"), d(count, "font-weight"), d(count, "color")]).toEqual([
      "15px",
      "700",
      "var(--ink3)",
    ]);
    const intro = [...root.querySelectorAll("p")].find((e) => text(e) === COPY.intro) as Element;
    expect([d(intro, "font-size"), d(intro, "font-weight"), d(intro, "color")]).toEqual([
      "15.5px",
      "600",
      "var(--ink2)",
    ]);
  });

  it("WEB_10_team_styles_invite_field_is_280_by_42_and_the_button_dims_until_valid", async () => {
    const { root } = await renderTeam(makeApp());
    const field = inputNamed(root, "Invite by email").parentElement as HTMLElement;
    expect([d(field, "height"), d(field, "width"), d(field, "border-radius")]).toEqual([
      "42px",
      "280px",
      "12px",
    ]);
    expect([bg(field), d(field, "border")]).toEqual(["var(--field)", "1px solid var(--line)"]);
    const button = [...root.querySelectorAll("button")].find(
      (b) => text(b) === COPY.invite,
    ) as Element;
    expect(d(button, "opacity"), "invalid email: 60%").toBe(".6");
    await typeInto(inputNamed(root, "Invite by email"), "a@b.co");
    expect(["", "1"], "valid email: full").toContain(d(button, "opacity"));
  });
});

describe("WEB_10_team_styles: members table", () => {
  it("WEB_10_team_styles_members_header_and_person_rows_use_the_design_grid", async () => {
    const { root } = await renderTeam(makeApp());
    const rows = rowsOf(region(root, "Members"));
    const [head, ...people] = rows as [HTMLElement, ...HTMLElement[]];
    expect(d(head, "grid-template-columns")).toBe(MEMBERS_COLS);
    expect(gaps(head, rules())[1]).toBe(16);
    expect(d(head, "height")).toBe("36px");
    expect([d(head, "font-size"), d(head, "font-weight"), d(head, "letter-spacing")]).toEqual([
      "12px",
      "800",
      ".6px",
    ]);
    expect(d(head, "color")).toBe("var(--ink3)");
    expect(people).toHaveLength(PEOPLE.length);
    for (const row of people) {
      expect(d(row, "grid-template-columns")).toBe(MEMBERS_COLS);
      expect(gaps(row, rules())[1]).toBe(16);
      expect(d(row, "min-height")).toBe("64px");
    }
  });

  it("WEB_10_team_styles_members_table_is_820_wide_and_scrolls_sideways_inside_its_card", async () => {
    const { root } = await renderTeam(makeApp());
    const members = region(root, "Members");
    const row = rowsOf(members)[0] as HTMLElement;
    let table: HTMLElement | null = null;
    for (let e = row.parentElement; e && e !== members; e = e.parentElement) {
      if (d(e, "min-width") === "820px") table = e;
    }
    expect(table, "an element of min-width 820px wraps the rows").not.toBeNull();
    expect(d(table?.parentElement as Element, "overflow-x")).toBe("auto");
  });

  it("WEB_10_team_styles_person_avatar_40px_round_and_more_button_36px", async () => {
    const { root } = await renderTeam(makeApp());
    const row = rowsOf(region(root, "Members"))[1] as HTMLElement;
    const avatar = [...row.querySelectorAll("*")].find((e) => ownText(e) === "AM") as Element;
    expect([d(avatar, "width"), d(avatar, "height"), d(avatar, "border-radius")]).toEqual([
      "40px",
      "40px",
      "999px",
    ]);
    const more = row.querySelector("button[aria-label^='Show details for']") as Element;
    expect([d(more, "width"), d(more, "height"), d(more, "border-radius")]).toEqual([
      "36px",
      "36px",
      "10px",
    ]);
  });
});

describe("WEB_10_team_styles: coverage, rules and matrix", () => {
  it("WEB_10_team_styles_coverage_rows_grid_gap_padding_and_the_slow_wait_in_amber", async () => {
    const { root } = await renderTeam(makeApp());
    const rows = rowsOf(region(root, "Approval coverage"));
    expect(rows).toHaveLength(COVERAGE.length);
    rows.forEach((row, i) => {
      expect(d(row, "grid-template-columns")).toBe(COVER_COLS);
      expect(gaps(row, rules())).toEqual([14, 14]);
      expect(d(row, "padding")).toBe("12px 0");
      expect(d(row, "border-top")).toBe("1px solid var(--line2)");
      const wait = kids(row)[2] as Element;
      expect(d(wait, "color"), `${COVERAGE[i]?.what}: wait colour`).toBe(
        COVERAGE[i]?.id === "share" ? "var(--amberink)" : "var(--ink)",
      );
    });
  });

  it("WEB_10_team_styles_approver_avatars_30px_overlap_by_6", async () => {
    const { root } = await renderTeam(makeApp());
    const first = rowsOf(region(root, "Approval coverage"))[0] as HTMLElement;
    const av = [...first.querySelectorAll("[title]")] as HTMLElement[];
    expect(av).toHaveLength(2);
    for (const a of av) {
      expect([d(a, "width"), d(a, "height"), d(a, "border-radius")]).toEqual([
        "30px",
        "30px",
        "99px",
      ]);
      expect(d(a, "margin-right")).toBe("-6px");
    }
  });

  it("WEB_10_team_styles_rule_art_tile_44_r13_amber_and_lower_cards_share_a_2_up_grid", async () => {
    const { root } = await renderTeam(makeApp());
    const rulesCard = region(root, "Approval rules");
    const tile = [...rulesCard.querySelectorAll("*")].find(
      (e) =>
        d(e, "width") === "44px" && d(e, "height") === "44px" && d(e, "border-radius") === "13px",
    );
    expect(tile, "44px tile, radius 13").toBeDefined();
    expect(tile && bg(tile)).toBe("var(--ambertile)");
    expect(tile?.querySelector("img") ?? null).not.toBeNull();
    const grid = rulesCard.parentElement as HTMLElement;
    expect(grid.contains(region(root, "What each role can do"))).toBe(true);
    expect(d(grid, "grid-template-columns")).toBe("repeat(auto-fit,minmax(min(100%,420px),1fr))");
    expect(gaps(grid, rules())[1]).toBe(18);
    expect(d(grid, "align-items")).toBe("start");
  });

  it("WEB_10_team_styles_matrix_grid_row_heights_and_check_boxes", async () => {
    const { root } = await renderTeam(makeApp());
    const rows = rowsOf(region(root, "What each role can do"));
    const [head, ...body] = rows as [HTMLElement, ...HTMLElement[]];
    expect(d(head, "grid-template-columns")).toBe(MATRIX_COLS);
    expect(d(head, "height")).toBe("32px");
    expect(body).toHaveLength(MATRIX.length);
    for (const row of body) {
      expect(d(row, "grid-template-columns")).toBe(MATRIX_COLS);
      expect(d(row, "min-height")).toBe("40px");
    }
    const cells = [...(body[0] as HTMLElement).querySelectorAll("[data-granted]")];
    for (const c of cells) {
      const on = c.getAttribute("data-granted") === "true";
      expect([d(c, "width"), d(c, "height"), d(c, "border-radius")]).toEqual([
        "26px",
        "26px",
        "8px",
      ]);
      expect(bg(c)).toBe(on ? "var(--oksoft)" : "transparent");
      expect(d(c, "color")).toBe(on ? "var(--ok)" : "var(--track)");
    }
  });
});
