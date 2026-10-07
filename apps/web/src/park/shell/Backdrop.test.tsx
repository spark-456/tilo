// @vitest-environment happy-dom
// WEB-3b: the city backdrop (README "City backdrop"; reference `Tilo App.dc.html`: the scene is drawn
// once per `time|motion` and cached, its free `spots` become `app.pins`). It was static in WEB-3b; WEB-MOTION-1
// made it live (Backdrop.motion.test.tsx pins the motion choices; here only the draw count and pins). Mounted through <AppShell/> with the scene engine
// replaced by a fast stand-in (test-support/park/shellEngine.ts); the real scene is exercised in the browser spec.
// Pins, from the reference: three targets [1000,420] (min area 4), [820,640] (4), [900,250] (2); each takes
// the nearest unused free spot with at least that area, else stays at the target; then x = (px - 800) * scale
// + vw / 2 and y = (py - 500) * scale + vh / 2, with scale = max(vw / 1600, vh / 1000).
// The tests count builds as a difference per test, so they hold for a cache kept per mount or per document.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { sceneConfig, sceneSpy } from "../../../test-support/park/shellEngine";
import { mountApp, seen } from "../../../test-support/park/shellHarness";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  sceneConfig.spots = [];
});

const scene = () => q(document.body, '[data-testid="fake-scene"]');
const builds = () => sceneSpy.mock.calls.length;
const opts = (call: unknown[] | undefined) =>
  call?.[0] as { w?: number; h?: number; night?: boolean; still?: boolean } | undefined;
const spot = (x: number, y: number, area: number) => ({ x, y, area, st: "s" });
const near = (got: readonly { x: number; y: number }[], want: readonly [number, number][]) => {
  expect(got).toHaveLength(want.length);
  want.forEach(([x, y], i) => {
    expect(got[i]?.x, `pin ${i} x`).toBeCloseTo(x, 3);
    expect(got[i]?.y, `pin ${i} y`).toBeCloseTo(y, 3);
  });
};

describe("WEB_3b_backdrop: the city behind the page", () => {
  it("WEB_3b_backdrop_the_scene_is_drawn_once_inside_an_aria_hidden_layer_with_nothing_to_click", async () => {
    const { m } = await mountApp();
    expect(qa(m.container, '[data-testid="fake-scene"]')).toHaveLength(1);
    const layer = scene().closest('[aria-hidden="true"]') as HTMLElement;
    expect(layer).not.toBeNull();
    expect(layer.querySelector("a, button, input, select, textarea, [tabindex]")).toBeNull();
    expect(layer.contains(q(m.container, '[data-testid="kid"]'))).toBe(false);
  });

  it("WEB_3b_backdrop_a_theme_change_shows_a_night_scene_and_day_comes_back_from_the_cache", async () => {
    const { m } = await mountApp();
    const day = scene().getAttribute("data-build");
    expect(scene().getAttribute("data-night")).toBe("false");
    const before = builds();
    click(q(m.container, 'button[aria-label="Switch to night"]'));
    expect(scene().getAttribute("data-night")).toBe("true");
    expect(scene().getAttribute("data-build")).not.toBe(day);
    expect(builds() - before).toBeLessThanOrEqual(1);
    const mid = builds();
    click(q(m.container, 'button[aria-label="Switch to day"]'));
    expect(builds()).toBe(mid); // no third build
    expect(scene().getAttribute("data-build")).toBe(day); // the same scene as before
    expect(scene().getAttribute("data-night")).toBe("false");
  });

  it("WEB_3b_backdrop_night_is_asked_for_with_night_true_and_day_with_night_false", async () => {
    const { m } = await mountApp();
    click(q(m.container, 'button[aria-label="Switch to night"]'));
    const nights = sceneSpy.mock.calls.map((c) => opts(c)?.night);
    expect(nights).toContain(false);
    expect(nights).toContain(true);
  });

  it("WEB_3b_backdrop_unrelated_changes_never_redraw_the_city", async () => {
    const { m } = await mountApp();
    const start = builds();
    const build = scene().getAttribute("data-build");
    act(() => seen.app.decide("depot"));
    click(q(m.container, 'button[aria-label="Notifications"]'));
    click(q(m.container, 'button[aria-label="Account menu"]'));
    act(() => seen.app.toast("hi"));
    expect(builds()).toBe(start);
    expect(scene().getAttribute("data-build")).toBe(build);
  });

  it("WEB_3b_backdrop_every_scene_asked_for_is_the_1600_by_1000_one_and_the_default_is_live", async () => {
    // WEB-MOTION-1: the city is live (still false) unless the person, the OS or the device says otherwise.
    await mountApp();
    expect(sceneSpy.mock.calls.length).toBeGreaterThan(0);
    for (const c of sceneSpy.mock.calls) {
      expect(opts(c)).toMatchObject({ w: 1600, h: 1000 });
    }
    expect(opts(sceneSpy.mock.calls[0])?.still).toBe(false);
  });
});

describe("WEB_3b_pins: the scene's free spots become app.pins", () => {
  it("WEB_3b_pins_exact_spots_map_to_screen_space_and_follow_a_resize_without_a_redraw", async () => {
    sceneConfig.spots = [spot(1000, 420, 4), spot(820, 640, 4), spot(900, 250, 2)];
    const { resize } = await mountApp({ viewport: { vw: 1440, vh: 900 } });
    act(() => seen.app.setPref("motion", "calm")); // a key no other test has used, so it is drawn here
    near(seen.app.pins, [
      [900, 378],
      [738, 576],
      [810, 225],
    ]);
    const drawn = builds();
    resize(390, 844); // scale max(390/1600, 844/1000) = 0.844
    near(seen.app.pins, [
      [363.8, 354.48],
      [211.88, 540.16],
      [279.4, 211],
    ]);
    expect(builds()).toBe(drawn);
  });

  it("WEB_3b_pins_a_spot_that_is_too_small_is_skipped_and_a_spot_is_used_only_once", async () => {
    sceneConfig.spots = [spot(1000, 420, 3), spot(1010, 430, 4)];
    await mountApp({ viewport: { vw: 1600, vh: 1000 } });
    act(() => seen.app.setPref("motion", "still"));
    // target 1 (min 4) takes the area-4 spot; target 2 (min 4) finds none and stays; target 3 (min 2) takes the area-3 spot
    near(seen.app.pins, [
      [1010, 430],
      [820, 640],
      [1000, 420],
    ]);
  });

  it("WEB_3b_pins_with_no_free_spot_the_three_targets_are_used", async () => {
    sceneConfig.spots = [];
    await mountApp({ viewport: { vw: 1600, vh: 1000 } });
    act(() => seen.app.setPref("time", "night"));
    act(() => seen.app.setPref("motion", "calm"));
    near(seen.app.pins, [
      [1000, 420],
      [820, 640],
      [900, 250],
    ]);
  });

  it("WEB_3b_pins_each_target_takes_the_nearest_free_spot", async () => {
    sceneConfig.spots = [spot(700, 700, 9), spot(995, 425, 9), spot(1100, 300, 9)];
    await mountApp({ viewport: { vw: 1600, vh: 1000 } });
    act(() => seen.app.setPref("time", "night"));
    act(() => seen.app.setPref("motion", "still"));
    near(seen.app.pins, [
      [995, 425],
      [700, 700],
      [1100, 300],
    ]);
  });
});

// Last on purpose: it uses the day|calm key, which the pin tests above fill with their own spots first.
describe("WEB_3b_motion: motion is part of the cache key", () => {
  it("WEB_3b_motion_a_motion_change_is_a_new_cache_key_and_the_first_comes_back_unchanged", async () => {
    await mountApp();
    const calm = scene().getAttribute("data-build");
    act(() => seen.app.setPref("motion", "lively"));
    expect(scene().getAttribute("data-build")).not.toBe(calm);
    act(() => seen.app.setPref("motion", "calm"));
    expect(scene().getAttribute("data-build")).toBe(calm);
  });
});
