// @vitest-environment happy-dom
// WEB-CUTOVER acceptance: a world has a stage only when its data came from the live API. "Open live view" and
// the Story / Trace / Delivery / Inspect links of a sample (fixture) world are the same elements, disabled:
// no href, aria-disabled, the reason as a title and as visually-hidden text. A live-source world links the
// stage routes as before (docs/park-designed-not-in-prd/World.md).
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, qa } from "../../../../test-support/park/componentsHarness";
import {
  clickEl,
  control,
  goCalls,
  mountWorld,
  pageText,
  spiedApi,
  textOf,
} from "../../../../test-support/park/worldHarness";
import type { Api } from "../../api/index";

afterEach(cleanup);

const REASON = "Sample world: there is no recorded run to open";
const LENSES = ["Story", "Trace", "Delivery", "Inspect"] as const;

/** The fixture Api whose world list reports `source: "live"`, as the live Api's does. */
function liveWorlds(): Api {
  const base = spiedApi();
  return {
    ...base,
    getWorlds: async (...a: Parameters<typeof base.getWorlds>) => ({
      ...(await base.getWorlds(...a)),
      source: "live" as const,
    }),
  } as Api;
}

const lensNav = (el: HTMLElement) => el.querySelector('nav[aria-label="Run views"]') as HTMLElement;

describe("WEB_CUTOVER_world_stage: a sample world has no stage to open", () => {
  it("WEB_CUTOVER_world_stage_sample_open_live_view_is_disabled_with_the_reason", async () => {
    const { el } = await mountWorld();
    const live = control(el, "Open live view");
    expect(live.hasAttribute("href")).toBe(false);
    expect(live.getAttribute("aria-disabled")).toBe("true");
    expect(live.getAttribute("role")).toBe("link");
    expect(live.getAttribute("title")).toBe(REASON);
    expect(live.className).toContain("park-world-live");
    expect(live.querySelector("svg"), "the play icon stays").not.toBeNull();
    const hidden = qa(el, `#${live.getAttribute("aria-describedby")}`);
    expect(hidden).toHaveLength(1);
    expect(textOf(hidden[0] as HTMLElement)).toBe(REASON);
  });

  it("WEB_CUTOVER_world_stage_sample_lens_links_are_disabled_with_the_reason", async () => {
    const { el } = await mountWorld();
    const nav = lensNav(el);
    expect(nav).not.toBeNull();
    for (const name of LENSES) {
      const a = control(nav, name);
      expect(a.hasAttribute("href"), name).toBe(false);
      expect(a.getAttribute("aria-disabled"), name).toBe("true");
      expect(a.getAttribute("role"), name).toBe("link");
      expect(a.getAttribute("title"), name).toBe(REASON);
      expect(qa(el, `#${a.getAttribute("aria-describedby")}`), name).toHaveLength(1);
    }
    expect(pageText(el)).toContain(REASON);
  });

  it("WEB_CUTOVER_world_stage_sample_no_link_leads_to_a_stage_route", async () => {
    const { el } = await mountWorld();
    expect(qa(el, 'a[href^="/world/"]')).toHaveLength(0);
  });

  it("WEB_CUTOVER_world_stage_clicking_a_disabled_link_goes_nowhere", async () => {
    const rig = await mountWorld();
    const before = window.location.pathname;
    for (const label of ["Open live view", ...LENSES]) clickEl(control(rig.el, label));
    expect(window.location.pathname).toBe(before);
    expect(goCalls(rig.app)).toBe(0);
  });

  it("WEB_CUTOVER_world_stage_a_world_started_here_has_no_stage_even_from_a_live_list", async () => {
    // A world the composer started is local state (app.added); no run exists for it whatever the list says.
    const api = liveWorlds();
    const started = (await api.getWorlds({}, [])).data.find((w) => w.id === "hires");
    if (!started) throw new Error("no hires world in the list");
    const { el } = await mountWorld({ id: "hires", api, added: [started] });
    expect(control(el, "Open live view").hasAttribute("href")).toBe(false);
  });
});

describe("WEB_CUTOVER_world_stage: a live-source world links its stage", () => {
  it("WEB_CUTOVER_world_stage_live_open_live_view_is_the_stage_link", async () => {
    const { el } = await mountWorld({ api: liveWorlds() });
    const live = control(el, "Open live view");
    expect(live.tagName).toBe("A");
    expect(live.getAttribute("href")).toBe("/world/k1/stage");
    expect(live.hasAttribute("aria-disabled")).toBe(false);
    expect(live.hasAttribute("title")).toBe(false);
    expect(live.querySelector("svg"), "the play icon").not.toBeNull();
    expect(pageText(el)).not.toContain(REASON);
  });

  it("WEB_CUTOVER_world_stage_live_the_lenses_link_story_trace_delivery_and_inspect", async () => {
    const { el } = await mountWorld({ api: liveWorlds() });
    const hrefs = qa<HTMLAnchorElement>(lensNav(el), "a").map((a) => a.getAttribute("href"));
    expect(hrefs.slice(0, 3)).toEqual(["/world/k1/story", "/world/k1/trace", "/world/k1/delivery"]);
    expect(hrefs[3]).toMatch(/^\/world\/k1\/inspect\/[^/]+$/);
  });

  it("WEB_CUTOVER_world_stage_live_the_links_use_the_second_city_id_and_never_app_go", async () => {
    const rig = await mountWorld({ id: "hires", api: liveWorlds() });
    expect(control(rig.el, "Open live view").getAttribute("href")).toBe("/world/hires/stage");
    for (const a of qa<HTMLAnchorElement>(rig.el, 'a[href^="/world/"]')) {
      clickEl(a);
      clickEl(a, { ctrlKey: true });
    }
    expect(goCalls(rig.app)).toBe(0);
  });

  it("WEB_CUTOVER_world_stage_live_a_town_and_a_village_still_have_no_live_view", async () => {
    for (const id of ["northline", "calls"]) {
      const { el } = await mountWorld({ id, api: liveWorlds() });
      expect(pageText(el), id).not.toContain("Open live view");
      cleanup();
    }
  });
});
