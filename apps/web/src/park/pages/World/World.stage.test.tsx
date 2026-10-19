// @vitest-environment happy-dom
// WEB-CUTOVER acceptance: a world has a stage only when its data came from the live API. A sample (fixture) world
// offers no "Open live view" and no Story / Trace / Delivery / Inspect links (POLISH-2; they were disabled links
// before) and says why in one chip. A live-source world links the stage routes as before
// (docs/park-designed-not-in-prd/World.md).
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, qa } from "../../../../test-support/park/componentsHarness";
import {
  clickEl,
  control,
  goCalls,
  hasControl,
  liveWorldsApi,
  mountWorld,
  pageText,
  spiedApi,
  textOf,
} from "../../../../test-support/park/worldHarness";

afterEach(cleanup);

const REASON = "Live view is for real runs";
const LENSES = ["Story", "Trace", "Delivery", "Inspect"] as const;

const lensNav = (el: HTMLElement) => el.querySelector('nav[aria-label="Run views"]') as HTMLElement;

// POLISH-2: a sample world does not show a greyed-out live view or lens links (they read as broken). It shows no stage
// controls and one visible chip with the reason. (Before: the same elements, disabled, with the reason as a title.)
describe("WEB_CUTOVER_world_stage: a sample world has no stage to open", () => {
  it("WEB_CUTOVER_world_stage_sample_open_live_view_is_disabled_with_the_reason", async () => {
    const { el } = await mountWorld();
    expect(hasControl(el, "Open live view")).toBe(false);
    expect(qa(el, "a.park-world-live")).toHaveLength(0);
    expect(pageText(el)).toContain(REASON);
  });

  it("WEB_CUTOVER_world_stage_sample_lens_links_are_disabled_with_the_reason", async () => {
    const { el } = await mountWorld();
    expect(lensNav(el)).toBeNull();
    const links = qa(el, "a").map(textOf);
    for (const name of LENSES) expect(links, name).not.toContain(name);
    expect(pageText(el)).toContain(REASON);
  });

  it("UI_10_B4_disabled_lens_links_and_live_view_are_keyboard_focusable_and_the_reason_is_visible", async () => {
    const { el } = await mountWorld();
    // nothing is left disabled to tab to; the reason is words on the page (a chip), not a tooltip or hidden text
    expect(qa(el, 'a[aria-disabled="true"]')).toHaveLength(0);
    const reason = qa(el, ".park-world-nostage");
    expect(reason).toHaveLength(1);
    expect(textOf(reason[0] as HTMLElement)).toBe(REASON);
    expect(reason[0]?.classList.contains("park-world-sr")).toBe(false);
  });

  it("WEB_CUTOVER_world_stage_sample_no_link_leads_to_a_stage_route", async () => {
    const { el } = await mountWorld();
    expect(qa(el, 'a[href^="/world/"]')).toHaveLength(0);
  });

  it("WEB_CUTOVER_world_stage_clicking_a_disabled_link_goes_nowhere", async () => {
    const rig = await mountWorld();
    const before = window.location.pathname;
    expect(hasControl(rig.el, "Open live view")).toBe(false);
    expect(qa(rig.el, "a").map(textOf)).not.toContain("Story");
    expect(window.location.pathname).toBe(before);
    expect(goCalls(rig.app)).toBe(0);
  });

  it("WEB_CUTOVER_world_stage_a_world_started_here_has_no_stage_even_from_a_live_list", async () => {
    // A world the composer started is local state (app.added); no run exists for it whatever the list says.
    const api = liveWorldsApi();
    const started = (await api.getWorlds({}, [])).data.find((w) => w.id === "hires");
    if (!started) throw new Error("no hires world in the list");
    const { el } = await mountWorld({ id: "hires", api, added: [started] });
    expect(hasControl(el, "Open live view")).toBe(false);
    expect(pageText(el)).toContain(REASON);
  });
});

describe("WEB_CUTOVER_world_stage: a live-source world links its stage", () => {
  it("WEB_CUTOVER_world_stage_live_open_live_view_is_the_stage_link", async () => {
    const { el } = await mountWorld({ api: liveWorldsApi() });
    const live = control(el, "Open live view");
    expect(live.tagName).toBe("A");
    expect(live.getAttribute("href")).toBe("/world/k1/stage");
    expect(live.hasAttribute("aria-disabled")).toBe(false);
    expect(live.hasAttribute("title")).toBe(false);
    expect(live.querySelector("svg"), "the play icon").not.toBeNull();
    expect(pageText(el)).not.toContain(REASON);
  });

  it("WEB_CUTOVER_world_stage_live_the_lenses_link_story_trace_delivery_and_inspect", async () => {
    const { el } = await mountWorld({ api: liveWorldsApi() });
    const hrefs = qa<HTMLAnchorElement>(lensNav(el), "a").map((a) => a.getAttribute("href"));
    expect(hrefs.slice(0, 3)).toEqual(["/world/k1/story", "/world/k1/trace", "/world/k1/delivery"]);
    expect(hrefs[3]).toMatch(/^\/world\/k1\/inspect\/[^/]+$/);
  });

  it("WEB_CUTOVER_world_stage_live_the_links_use_the_second_city_id_and_never_app_go", async () => {
    const rig = await mountWorld({ id: "hires", api: liveWorldsApi() });
    expect(control(rig.el, "Open live view").getAttribute("href")).toBe("/world/hires/stage");
    for (const a of qa<HTMLAnchorElement>(rig.el, 'a[href^="/world/"]')) {
      clickEl(a);
      clickEl(a, { ctrlKey: true });
    }
    expect(goCalls(rig.app)).toBe(0);
  });

  // LIVE-QA-1 (9b382ba2, the user's order): every live world, whatever its size, has the live view and the lenses.
  it("LIVE_QA_1_world_stage_live_a_town_and_a_village_also_have_the_live_view_and_lenses", async () => {
    for (const id of ["northline", "calls"]) {
      const { el } = await mountWorld({ id, api: liveWorldsApi() });
      const live = control(el, "Open live view");
      expect(live.tagName, id).toBe("A");
      expect(live.getAttribute("href"), id).toBe(`/world/${id}/stage`);
      const hrefs = qa<HTMLAnchorElement>(lensNav(el), "a").map((a) => a.getAttribute("href"));
      expect(hrefs.slice(0, 3), id).toEqual([
        `/world/${id}/story`,
        `/world/${id}/trace`,
        `/world/${id}/delivery`,
      ]);
      cleanup();
    }
  });
});
