// @vitest-environment happy-dom
// WORLD-DESIGN (design/studio-v2 "Tilo S World.dc.html"): the World page without a card around it, the city map with
// its building names and district tags, the + / - zoom buttons, the card that says the newest recorded line (and
// nothing invented), a Story pane that never cuts off silently, and the lens rows that scroll sideways on a phone.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../../test-support/park/componentsHarness";
import { stripComments } from "../../../../test-support/park/css";
import { liveWorldsApi, mountWorld } from "../../../../test-support/park/worldHarness";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { HttpClient } from "../../../api/http";
import type { ActivityItem, Plan } from "../../api/types";
import { latestLine } from "./MapChrome";
import { storyOf } from "./runSteps";
import type { RunEvent } from "./useRunEvents";
import { labelledCityArt } from "./worldArt";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const read = (rel: string) => readFileSync(join(__dirname, rel), "utf8");
const ev = (seq: number, type: string, summary: string, ts = "2026-10-12T11:52:00Z"): RunEvent => ({
  seq,
  type,
  ts,
  credits: 0,
  summary,
});

describe("FR_WLD_04 the card on the map says only the newest recorded line", () => {
  it("test_FR_WLD_04_latest_line_of_a_run_is_its_newest_story_event_with_its_recorded_time", () => {
    const line = latestLine(
      [
        ev(1, "world.started", "The run began."),
        ev(2, "building.completed", "Fuel and tolls are costed.", "2026-10-12T11:58:30Z"),
        ev(3, "run.noise", "Not in the story family."),
      ],
      undefined,
    );
    expect(line).toEqual({
      text: "Fuel and tolls are costed.",
      meta: "Latest recorded · 11:58 UTC",
      kind: "done",
    });
  });

  it("test_FR_WLD_04_latest_line_says_nothing_when_nothing_is_recorded", () => {
    expect(latestLine([], undefined)).toBeNull();
    expect(latestLine([ev(1, "run.noise", "x")], [])).toBeNull();
    // a real run with no events never borrows a sample world's activity
    const activity: ActivityItem[] = [
      { t: "11:52", who: "Builder", text: "Did a thing.", kind: "info" },
    ];
    expect(latestLine([], activity)).toBeNull();
    expect(latestLine(null, undefined)).toBeNull();
  });

  it("test_FR_WLD_04_latest_line_of_a_list_world_is_the_first_activity_item_and_asking_events_say_needs", () => {
    const activity: ActivityItem[] = [
      { t: "11:52", who: "Builder", text: "Paused Laptop Depot.", kind: "needs" },
      { t: "11:40", who: "Courier", text: "Drafted a brief.", kind: "done" },
    ];
    expect(latestLine(null, activity)).toEqual({
      text: "Paused Laptop Depot.",
      meta: "Builder · 11:52",
      kind: "needs",
    });
    expect(
      latestLine([ev(1, "approval.requested", "Waiting for your yes.")], undefined)?.kind,
    ).toBe("needs");
  });

  it("test_FR_WLD_04_the_world_page_shows_the_list_worlds_own_latest_activity", async () => {
    const rig = await mountWorld({ id: "k1" });
    const toast = q(rig.el, ".park-world-toast");
    expect(toast.tagName).toBe("OUTPUT");
    expect(toast.textContent).toContain("Paused Laptop Depot.");
    expect(toast.textContent).toContain("Builder · 11:52");
  });

  it("test_FR_WLD_04_a_live_runs_toast_is_the_newest_recorded_story_sentence", async () => {
    const api = liveWorldsApi();
    const rows = EVENTS_VILLAGE_BASIC.map((e) => ({ ...e, world_id: "hires" }));
    const fetch = vi.fn(async (url: string | URL | Request) =>
      String(url).includes("/events")
        ? new Response(JSON.stringify({ events: rows }))
        : new Response("{}", { status: 404 }),
    );
    const client = new HttpClient({ baseUrl: "https://api.test", fetch, pollMs: 60_000 });
    const rig = await mountWorld({ id: "hires", api, client });
    const newest = storyOf(rows as unknown as RunEvent[])[0];
    expect(newest).toBeDefined();
    expect(q(rig.el, ".park-world-toast").textContent).toContain(newest?.summary.trim());
  });
});

describe("FR_WLD_11 the city map: names, zoom, keyboard", () => {
  it("test_FR_WLD_11_a_city_has_zoom_buttons_that_resize_the_picture_and_make_it_scrollable", async () => {
    const rig = await mountWorld({ id: "k1" });
    const zoom = q(rig.el, ".park-world-zoom");
    const [inBtn, outBtn] = qa(zoom, "button");
    expect(inBtn?.getAttribute("aria-label")).toBe("Zoom in");
    expect(outBtn?.getAttribute("aria-label")).toBe("Zoom out");
    expect(outBtn?.getAttribute("aria-disabled")).toBe("true");
    expect(q(rig.el, ".park-world-pan").getAttribute("tabindex")).toBeNull();

    click(inBtn as Element);
    expect(zoom.textContent).toContain("Map at 150%");
    expect(q(rig.el, ".park-world-zoomed").getAttribute("style")).toContain("width: 150%");
    const pan = q(rig.el, ".park-world-pan");
    expect(pan.getAttribute("role")).toBe("region");
    expect(pan.getAttribute("tabindex")).toBe("0");
    expect(outBtn?.getAttribute("aria-disabled")).toBeNull();

    click(outBtn as Element);
    expect(zoom.textContent).toContain("Map at 100%");
    expect(q(rig.el, ".park-world-pan").getAttribute("tabindex")).toBeNull();
  });

  it("test_FR_WLD_11_a_town_has_no_zoom_buttons_and_its_art_is_not_wrapped", async () => {
    const rig = await mountWorld({ id: "northline" });
    expect(rig.el.querySelector(".park-world-zoom")).toBeNull();
    expect(rig.el.querySelector(".park-world-pan")).toBeNull();
  });

  it("test_FR_WLD_11_the_city_is_drawn_with_building_names_and_district_tags_from_the_plan", async () => {
    const calls: unknown[] = [];
    const { parkKit } = await import("../../shell/kit");
    const { plans } = await import("../../api/fixtures/worlds");
    const world = parkKit().TP.world;
    vi.spyOn(parkKit().TP, "world").mockImplementation((plan, o) => {
      calls.push(o);
      return world(plan, o);
    });
    // a plan the picture cache has not seen: wide maps ask for names and tags, narrow ones for tags only
    const plan = Object.assign({}, plans().k1, { note: "wd-labels" }) as Plan;
    labelledCityArt(plan, false, true);
    labelledCityArt(plan, false, false);
    labelledCityArt(plan, false, true);
    expect(calls).toEqual([
      expect.objectContaining({ night: false, labels: true, tags: true }),
      expect.objectContaining({ night: false, labels: false, tags: true }),
    ]);
  });
});

describe("FR_WLD_13 the page is not a card inside a card; the phone rows scroll sideways", () => {
  const studio = read("World.studio.css");
  const view = read("../../../worldView/WorldView.css");

  it("test_FR_WLD_13_the_studio_sheet_has_no_background_border_or_shadow_of_its_own", () => {
    const rule = /\.park-world-root > \.park-sheet \{([^}]*)\}/.exec(studio)?.[1] ?? "";
    expect(rule).toContain("background: transparent");
    expect(rule).toContain("border: 0");
    expect(rule).toContain("box-shadow: none");
  });

  it("test_FR_WLD_13_the_map_lens_links_and_the_world_story_trace_delivery_tabs_are_one_scrolling_row", () => {
    const lenses = /\.park-world-map \.park-world-lenses \{([^}]*)\}/.exec(studio)?.[1] ?? "";
    expect(lenses).toContain("flex-wrap: nowrap");
    expect(lenses).toContain("overflow-x: auto");
    const tabs =
      /\[data-park\] \.park-view-tabs \{([^}]*)\}/.exec(
        view.slice(view.indexOf("Phone targets")),
      )?.[1] ?? "";
    expect(tabs).toContain("flex-wrap: nowrap");
    expect(tabs).toContain("overflow-x: auto");
  });

  it("test_FR_WLD_13_nothing_in_the_new_stylesheet_animates", () => {
    expect(stripComments(studio)).not.toMatch(/transition|animation|@keyframes/);
  });
});

describe("FR_WLD_11 a long Story pane is reachable and says there is more", () => {
  it("test_FR_WLD_11_a_panel_that_scrolls_is_a_labelled_focus_stop_with_a_fade_until_its_end", async () => {
    const rig = await mountWorld({ id: "k1" });
    const body = q(rig.el, '[data-tab="story"] .park-world-panelbody');
    // happy-dom has no layout: stand a taller content in for it, then scroll
    Object.defineProperty(body, "scrollHeight", { configurable: true, value: 900 });
    Object.defineProperty(body, "clientHeight", { configurable: true, value: 500 });
    const scrollTo = (top: number) =>
      act(() => {
        body.scrollTop = top;
        body.dispatchEvent(new Event("scroll"));
      });
    scrollTo(0);
    expect(body.getAttribute("tabindex")).toBe("0");
    expect(body.getAttribute("role")).toBe("region");
    expect(rig.el.querySelector('[data-tab="story"] .park-world-fade')).not.toBeNull();
    scrollTo(400);
    expect(rig.el.querySelector('[data-tab="story"] .park-world-fade')).toBeNull();
  });
});
