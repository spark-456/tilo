// @vitest-environment happy-dom
// UI-STUDIO-INT: with Chat and Needs you added (design/studio-v2 "Tilo S Nav") the eight tabs no longer fit beside
// the tools between 840px and about 1100px. The tabs that do not fit move into a More menu, lowest priority first;
// below 840px the page menu stays; the strip never scrolls and the page never scrolls sideways.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp } from "../../../test-support/park/shellHarness";
import type { PageId } from "../app/AppCtx";
import { fitTabs, tabRoom, tabWidth } from "./navFit";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const TABS: readonly (readonly [PageId, string])[] = [
  ["home", "Home"],
  ["chat", "Chat"],
  ["worlds", "Worlds"],
  ["needs", "Needs you"],
  ["agenda", "Agenda"],
  ["skills", "Skills"],
  ["team", "Team"],
  ["connectors", "Connectors"],
  ["ledger", "Ledger"],
];
const ids = (tabs: readonly (readonly [PageId, string])[]) => tabs.map(([id]) => id);
const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ").trim();

describe("UI_STUDIO_INT navFit: which tabs fit", () => {
  it("UI_STUDIO_INT_every_tab_fits_from_1280_live_and_from_1440_beside_the_sample_chip", () => {
    for (const vw of [1280, 1440, 1920]) {
      expect(fitTabs(TABS, vw, { sample: false, badge: true }).more).toEqual([]);
    }
    for (const vw of [1440, 1920]) {
      expect(fitTabs(TABS, vw, { sample: true, badge: true }).more).toEqual([]);
    }
  });

  it("UI_STUDIO_INT_from_840_to_1199_the_shown_tabs_and_More_fit_the_room_and_keep_nav_order", () => {
    for (let vw = 840; vw < 1200; vw += 8) {
      for (const sample of [false, true]) {
        for (const badge of [false, true]) {
          const { shown, more } = fitTabs(TABS, vw, { sample, badge });
          expect([...ids(shown), ...ids(more)].sort()).toEqual(ids(TABS).sort());
          expect(ids(shown)).toEqual(ids(TABS).filter((id) => ids(shown).includes(id)));
          const used =
            shown.reduce((sum, [id, label]) => sum + tabWidth(id, label, badge, vw) + 2, 0) +
            (more.length > 0 ? 6 * 9 + 20 + 18 : 0);
          expect(used, `${vw}px`).toBeLessThanOrEqual(tabRoom(vw, sample));
          expect(ids(shown), "Home always stays").toContain("home");
        }
      }
    }
  });

  it("UI_STUDIO_INT_at_840_live_Home_Chat_Worlds_and_Needs_you_stay_the_rest_go_to_More", () => {
    const { shown, more } = fitTabs(TABS, 840, { sample: false, badge: true });
    expect(ids(shown)).toEqual(["home", "chat", "worlds", "needs"]);
    expect(ids(more)).toEqual(["agenda", "skills", "team", "connectors", "ledger"]);
  });

  it("UI_STUDIO_INT_an_unmeasured_window_shows_every_tab", () => {
    expect(fitTabs(TABS, 0, { sample: true, badge: true }).more).toEqual([]);
  });
});

describe("UI_STUDIO_INT the nav between 840 and 1199px", () => {
  const moreBtn = () => q<HTMLButtonElement>(document.body, "button.park-shell__more");

  it("UI_STUDIO_INT_900_shows_a_More_menu_with_the_tabs_that_do_not_fit_and_no_page_menu", async () => {
    const rig = await mountApp({ api: fakeApi(), viewport: { vw: 900, vh: 900 }, path: "/" });
    const strip = qa(rig.m.container, "header nav a").map(text);
    expect(strip.length).toBeGreaterThan(2);
    expect(strip.length).toBeLessThan(9);
    expect(document.body.querySelector("button.park-shell__pagebtn")).toBeNull();
    expect(moreBtn().getAttribute("aria-haspopup")).toBe("menu");
    click(moreBtn());
    const items = qa(document.body, '[role="menu"][aria-label="More pages"] [role="menuitem"]').map(
      (i) =>
        text(i)
          .replace(/Current page|\d+ decisions?/g, "")
          .trim(),
    );
    // every tab is either in the strip or in the menu, once
    expect([...strip.map((s) => s.replace(/\d+$/, "").trim()), ...items].sort()).toEqual(
      TABS.map(([, label]) => label).sort(),
    );
  });

  it("UI_STUDIO_INT_choosing_a_More_item_goes_there_and_the_button_then_names_that_page", async () => {
    const rig = await mountApp({ api: fakeApi(), viewport: { vw: 900, vh: 900 }, path: "/" });
    click(moreBtn());
    const team = qa(document.body, '[role="menuitem"]').find((i) => text(i).startsWith("Team"));
    click(team as Element);
    expect(rig.navigate).toHaveBeenLastCalledWith("/team");
    expect(document.body.querySelector('[role="menu"][aria-label="More pages"]')).toBeNull();
  });

  it("UI_STUDIO_INT_on_a_page_inside_More_the_button_says_its_name_and_is_marked_current", async () => {
    await mountApp({ api: fakeApi(), viewport: { vw: 900, vh: 900 }, path: "/team" });
    expect(text(moreBtn())).toContain("Team");
    expect(moreBtn().getAttribute("aria-label")).toMatch(/^More pages, now on Team/);
    expect(moreBtn().classList.contains("park-shell__tab--on")).toBe(true);
  });

  it("UI_STUDIO_INT_1440_has_all_nine_tabs_and_no_More", async () => {
    const rig = await mountApp({ api: fakeApi(), viewport: { vw: 1440, vh: 900 }, path: "/" });
    expect(qa(rig.m.container, "header nav a")).toHaveLength(9);
    expect(document.body.querySelector("button.park-shell__more")).toBeNull();
  });
});
