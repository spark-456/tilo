// @vitest-environment happy-dom
// WEB-4 acceptance: where Home leads (README "Cross-page links" and "Home"; inventory.md "Navigates to:
// world, worlds, agenda, ledger"). Navigation goes through `app.go` and nowhere else: no address-bar
// reads, no `decide` from Home (approvals happen on the world page), and every control is a real
// button or link that the keyboard reaches.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, press, qa } from "../../../../test-support/park/componentsHarness";
import { LIVE_OPEN, UP_NEXT } from "../../../../test-support/park/homeCopy";
import {
  clickEl,
  control,
  controlWith,
  goCalls,
  lastGo,
  mountHome,
  todayRegion,
} from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

// UI-STUDIO-2: the world cards and All worlds sit in the Sample worlds section, not in the Today column.
const worldsOf = (el: HTMLElement): HTMLElement =>
  el.querySelector('section[aria-label="Sample worlds"]') as HTMLElement;
const noParams = (p: unknown) =>
  p === undefined || (typeof p === "object" && p !== null && Object.keys(p).length === 0);

describe("WEB_4_home_links: each control goes where the reference sends it", () => {
  it("WEB_4_home_links_Review_opens_the_K1_world", async () => {
    const rig = await mountHome();
    clickEl(controlWith(rig.el, "in K1 electric scooter"));
    expect(lastGo(rig.app)).toEqual(["world", { id: "k1" }]);
    expect(goCalls(rig.app)).toBe(1);
  });

  it("WEB_4_home_links_a_live_row_opens_its_world", async () => {
    const rig = await mountHome();
    // CX-T-HOME: the two active sample worlds, then the recent finished one (Q3 audit prep) in the third card.
    for (const w of [...LIVE_OPEN.slice(0, 2), { id: "audit", name: "Q3 audit prep" }]) {
      clickEl(controlWith(worldsOf(rig.el), w.name));
      expect(lastGo(rig.app), w.name).toEqual(["world", { id: w.id }]);
    }
    expect(goCalls(rig.app)).toBe(3);
  });

  it("WEB_4_home_links_All_worlds_goes_to_the_worlds_page", async () => {
    const rig = await mountHome();
    const link = control(worldsOf(rig.el), "All worlds");
    const proceeded = clickEl(link);
    const last = lastGo(rig.app);
    expect(last?.[0]).toBe("worlds");
    expect(noParams(last?.[1])).toBe(true);
    if (link.tagName === "A")
      expect(proceeded, "the link must not load the old address").toBe(false);
    expect(goCalls(rig.app)).toBe(1);
  });

  it("WEB_4_home_links_Agenda_and_every_up_next_row_go_to_the_agenda", async () => {
    const rig = await mountHome();
    const link = control(todayRegion(rig.el), "Agenda");
    const proceeded = clickEl(link);
    expect(lastGo(rig.app)?.[0]).toBe("agenda");
    if (link.tagName === "A") expect(proceeded).toBe(false);
    for (const e of UP_NEXT) {
      clickEl(controlWith(todayRegion(rig.el), e.title));
      const last = lastGo(rig.app);
      expect(last?.[0], e.title).toBe("agenda");
      expect(noParams(last?.[1])).toBe(true);
    }
    expect(goCalls(rig.app)).toBe(1 + UP_NEXT.length);
  });

  it("WEB_4_home_links_the_spend_panel_goes_to_the_ledger", async () => {
    const rig = await mountHome();
    clickEl(controlWith(todayRegion(rig.el), "September spend"));
    const last = lastGo(rig.app);
    expect(last?.[0]).toBe("ledger");
    expect(noParams(last?.[1])).toBe(true);
    expect(goCalls(rig.app)).toBe(1);
  });
});

describe("WEB_4_home_links: nothing else moves the app", () => {
  it("WEB_4_home_links_Home_never_calls_decide_toast_or_setPref_by_itself", async () => {
    const rig = await mountHome();
    clickEl(controlWith(rig.el, "in K1 electric scooter"));
    clickEl(controlWith(todayRegion(rig.el), "September spend"));
    expect(rig.app.decide).not.toHaveBeenCalled();
    expect(rig.app.toast).not.toHaveBeenCalled();
    expect(rig.app.setPref).not.toHaveBeenCalled();
    expect(
      rig.navigate,
      "the page uses app.go, not the provider's navigate",
    ).not.toHaveBeenCalled();
  });

  it("WEB_4_home_links_a_click_leaves_the_address_bar_alone", async () => {
    const before = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    const rig = await mountHome();
    clickEl(control(worldsOf(rig.el), "All worlds"));
    clickEl(control(todayRegion(rig.el), "Agenda"));
    clickEl(controlWith(todayRegion(rig.el), "September spend"));
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe(
      before,
    );
  });

  it("WEB_4_home_links_every_action_is_a_native_button_or_a_link_with_an_href", async () => {
    const rig = await mountHome();
    const bad = qa(rig.el, '[role="button"], [role="link"], [onclick]').filter(
      (e) => e.tagName !== "BUTTON" && !(e.tagName === "A" && e.hasAttribute("href")),
    );
    expect(bad.map((e) => e.outerHTML.slice(0, 80))).toEqual([]);
    for (const a of qa(rig.el, "a"))
      expect(a.getAttribute("href"), a.textContent ?? "").toBeTruthy();
    for (const b of qa(rig.el, "button")) {
      expect(b.getAttribute("type"), b.textContent ?? "").toBe("button");
      // The sizes are one radio group with a roving tab stop (the component's contract); the rest tab.
      if (b.getAttribute("role") !== "radio") expect(b.getAttribute("tabindex")).not.toBe("-1");
    }
  });

  it("WEB_4_home_links_Enter_activates_Review_and_a_live_row", async () => {
    const rig = await mountHome();
    press(controlWith(rig.el, "in K1 electric scooter"), "Enter");
    expect(lastGo(rig.app)).toEqual(["world", { id: "k1" }]);
    press(controlWith(worldsOf(rig.el), "Onboard 12 new hires"), "Enter");
    expect(lastGo(rig.app)).toEqual(["world", { id: "hires" }]);
  });
});
