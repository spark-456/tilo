// @vitest-environment happy-dom
// WEB-3b: the static city backdrop (README "City backdrop"; reference `Tilo App.dc.html` bgScale, scene cache,
// pins). The city is STATIC here: no cars, walkers or animation (the motion restore is BQ-WEB-3).
// Pinned surface:
//   park/shell/sceneCache.ts: `createSceneCache(scene)`; `scene` is the engine's `scene(opts)`; returns
//     `get(time: "day"|"night", motion: Motion): { el; spots }`. One build per `time|motion` key, the same
//     object back for the same key. Each build calls scene({ w: 1600, h: 1000, vw: 1240, night, still: true }).
//   park/shell/pins.ts: `scenePins(spots, vw, vh): { x; y }[]`, the prototype's `pins`: three pins, picked from
//     the scene's free spots (nearest unused spot with at least `min` area to targets [1000,420] min 4,
//     [820,640] min 4, [900,250] min 2; the target itself when none is left), then moved to screen space:
//     x = (px - 800) * scale + vw / 2, y = (py - 500) * scale + vh / 2, scale = max(vw / 1600, vh / 1000).
//   park/shell/CityBackdrop.tsx: `CityBackdrop()`, no props. `div.park-backdrop[data-testid="park-backdrop"]
//     [aria-hidden="true"]` > `div.park-backdrop__scene` (inline `transform: scale(<max(vw/1600, vh/1000)>)`)
//     holding the scene element, and `div.park-backdrop__veil` on every page except home. The scene cache is
//     one per mounted backdrop (not module-global). It feeds store.setPins(scenePins(spots, vw, vh)), so
//     useApp().pins are those pins; a resize moves the pins without rebuilding the scene.
import fc from "fast-check";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../test-support/park/componentsHarness";
import { SCENE_SPOTS, sceneSpy } from "../../../test-support/park/shellEngine";
import { mountShell, seen } from "../../../test-support/park/shellHarness";
import type { Spot } from "../engines/types";
import { CityBackdrop } from "./CityBackdrop";
import { scenePins } from "./pins";
import { createSceneCache } from "./sceneCache";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

beforeEach(() => {
  sceneSpy.mockClear();
});
afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const spot = (x: number, y: number, area: number): Spot => ({ x, y, area, st: "s" });

describe("WEB_3b_cache: one scene per time|motion", () => {
  it("WEB_3b_cache_the_same_key_gives_the_same_object_and_builds_once", () => {
    const scene = vi.fn((_o?: unknown) => ({ el: {}, spots: [] as Spot[] }));
    const get = createSceneCache(scene);
    const a = get("day", "lively");
    expect(get("day", "lively")).toBe(a);
    expect(get("day", "lively")).toBe(a);
    expect(scene).toHaveBeenCalledTimes(1);
  });

  it("WEB_3b_cache_a_theme_change_builds_a_new_scene_and_going_back_reuses_the_first", () => {
    const scene = vi.fn((_o?: unknown) => ({ el: {}, spots: [] as Spot[] }));
    const get = createSceneCache(scene);
    const day = get("day", "calm");
    const night = get("night", "calm");
    expect(night).not.toBe(day);
    expect(scene).toHaveBeenCalledTimes(2);
    expect(get("day", "calm")).toBe(day);
    expect(get("night", "calm")).toBe(night);
    expect(scene).toHaveBeenCalledTimes(2);
  });

  it("WEB_3b_cache_the_key_includes_the_motion", () => {
    const scene = vi.fn((_o?: unknown) => ({ el: {}, spots: [] as Spot[] }));
    const get = createSceneCache(scene);
    for (const m of ["lively", "calm", "still"] as const) get("day", m);
    expect(scene).toHaveBeenCalledTimes(3);
    for (const m of ["lively", "calm", "still"] as const) get("day", m);
    expect(scene).toHaveBeenCalledTimes(3);
  });

  it("WEB_3b_cache_each_build_asks_for_a_still_1600_by_1000_scene_with_the_right_night_flag", () => {
    const scene = vi.fn((_o?: unknown) => ({ el: {}, spots: [] as Spot[] }));
    const get = createSceneCache(scene);
    get("day", "lively");
    get("night", "lively");
    expect(scene).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ w: 1600, h: 1000, night: false, still: true }),
    );
    expect(scene).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ w: 1600, h: 1000, night: true, still: true }),
    );
  });

  it("WEB_3b_cache_property_builds_equal_the_number_of_distinct_keys", () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.tuple(
            fc.constantFrom("day" as const, "night" as const),
            fc.constantFrom("lively" as const, "calm" as const, "still" as const),
          ),
          { maxLength: 30 },
        ),
        (calls) => {
          const scene = vi.fn((_o?: unknown) => ({ el: {}, spots: [] as Spot[] }));
          const get = createSceneCache(scene);
          const first = new Map<string, unknown>();
          for (const [t, m] of calls) {
            const v = get(t, m);
            const k = `${t}|${m}`;
            if (first.has(k)) expect(v).toBe(first.get(k));
            else first.set(k, v);
          }
          expect(scene).toHaveBeenCalledTimes(new Set(calls.map(([t, m]) => `${t}|${m}`)).size);
        },
      ),
    );
  });
});

describe("WEB_3b_pins: the scene's free spots become app.pins", () => {
  const exact = [spot(1000, 420, 4), spot(820, 640, 4), spot(900, 250, 2)];

  it("WEB_3b_pins_at_1600_by_1000_the_scale_is_one_and_exact_spots_map_to_themselves", () => {
    expect(scenePins(exact, 1600, 1000)).toEqual([
      { x: 1000, y: 420 },
      { x: 820, y: 640 },
      { x: 900, y: 250 },
    ]);
  });

  it("WEB_3b_pins_at_1440_by_900_the_scale_is_0_9_and_the_origin_is_the_viewport_centre", () => {
    const [a, b, c] = scenePins(exact, 1440, 900);
    expect(a?.x).toBeCloseTo((1000 - 800) * 0.9 + 720, 6);
    expect(a?.y).toBeCloseTo((420 - 500) * 0.9 + 450, 6);
    expect(b?.x).toBeCloseTo((820 - 800) * 0.9 + 720, 6);
    expect(b?.y).toBeCloseTo((640 - 500) * 0.9 + 450, 6);
    expect(c?.x).toBeCloseTo((900 - 800) * 0.9 + 720, 6);
    expect(c?.y).toBeCloseTo((250 - 500) * 0.9 + 450, 6);
  });

  it("WEB_3b_pins_the_larger_of_the_two_ratios_is_the_scale", () => {
    // 390 x 844: vw/1600 = 0.24375, vh/1000 = 0.844, so 0.844 wins (the city is cropped sideways)
    const [a] = scenePins(exact, 390, 844);
    expect(a?.x).toBeCloseTo((1000 - 800) * 0.844 + 195, 6);
    expect(a?.y).toBeCloseTo((420 - 500) * 0.844 + 422, 6);
  });

  it("WEB_3b_pins_a_spot_that_is_too_small_is_skipped_and_a_spot_is_used_once", () => {
    // near target 1 (min 4): the closer spot has area 3, so the farther one with area 4 is taken;
    // target 2 (min 4) has nothing left, so it stays at its own place; target 3 (min 2) takes the small one.
    const spots = [spot(1000, 420, 3), spot(1010, 430, 4)];
    expect(scenePins(spots, 1600, 1000)).toEqual([
      { x: 1010, y: 430 },
      { x: 820, y: 640 },
      { x: 1000, y: 420 },
    ]);
  });

  it("WEB_3b_pins_with_no_spots_the_three_targets_are_used", () => {
    expect(scenePins([], 1600, 1000)).toEqual([
      { x: 1000, y: 420 },
      { x: 820, y: 640 },
      { x: 900, y: 250 },
    ]);
  });

  it("WEB_3b_pins_the_nearest_spot_wins", () => {
    const spots = [spot(700, 700, 9), spot(995, 425, 9), spot(1100, 300, 9)];
    expect(scenePins(spots, 1600, 1000)[0]).toEqual({ x: 995, y: 425 });
  });

  it("WEB_3b_pins_property_always_three_finite_pins_and_never_changes_its_input", () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            x: fc.integer({ min: 0, max: 1600 }),
            y: fc.integer({ min: 0, max: 1000 }),
            area: fc.integer({ min: 0, max: 12 }),
            st: fc.constant("s"),
          }),
          { maxLength: 12 },
        ),
        fc.integer({ min: 320, max: 2560 }),
        fc.integer({ min: 480, max: 1440 }),
        (spots, vw, vh) => {
          const before = JSON.stringify(spots);
          const pins = scenePins(spots, vw, vh);
          expect(pins).toHaveLength(3);
          for (const p of pins) {
            expect(Number.isFinite(p.x)).toBe(true);
            expect(Number.isFinite(p.y)).toBe(true);
          }
          expect(JSON.stringify(spots)).toBe(before);
          expect(scenePins(spots, vw, vh)).toEqual(pins); // deterministic
        },
      ),
    );
  });
});

describe("WEB_3b_backdrop: the component", () => {
  const backdrop = (root: ParentNode) => q(root, '[data-testid="park-backdrop"]');
  const scaleOf = (root: ParentNode): number => {
    const t = q(root, ".park-backdrop__scene").style.transform;
    return Number(/scale\(([\d.]+)\)/.exec(t)?.[1]);
  };

  it("WEB_3b_backdrop_is_hidden_from_assistive_tech_and_holds_the_scene_once", () => {
    const { m } = mountShell(<CityBackdrop />);
    expect(qa(m.container, ".park-backdrop")).toHaveLength(1);
    expect(backdrop(m.container).getAttribute("aria-hidden")).toBe("true");
    expect(qa(backdrop(m.container), '[data-testid="fake-scene"]')).toHaveLength(1);
    expect(q(backdrop(m.container), ".park-backdrop__scene").contains(q(m.container, '[data-testid="fake-scene"]'))).toBe(true);
    expect(backdrop(m.container).querySelector("a, button, input, [tabindex]")).toBeNull();
  });

  it("WEB_3b_backdrop_builds_the_city_once_for_the_first_render", () => {
    mountShell(<CityBackdrop />);
    expect(sceneSpy).toHaveBeenCalledTimes(1);
    expect(sceneSpy).toHaveBeenCalledWith(
      expect.objectContaining({ w: 1600, h: 1000, night: false, still: true }),
    );
  });

  it("WEB_3b_backdrop_scales_by_the_larger_ratio_at_each_viewport", () => {
    for (const [vw, vh] of [
      [1440, 900],
      [1920, 1080],
      [390, 844],
      [1600, 1000],
    ] as const) {
      const { m } = mountShell(<CityBackdrop />, { viewport: { vw, vh } });
      expect(scaleOf(m.container), `${vw}x${vh}`).toBeCloseTo(Math.max(vw / 1600, vh / 1000), 3);
      m.unmount();
    }
  });

  it("WEB_3b_backdrop_a_resize_rescales_without_building_the_city_again", () => {
    const { m, resize } = mountShell(<CityBackdrop />, { viewport: { vw: 1440, vh: 900 } });
    expect(sceneSpy).toHaveBeenCalledTimes(1);
    resize(390, 844);
    expect(scaleOf(m.container)).toBeCloseTo(0.844, 3);
    expect(sceneSpy).toHaveBeenCalledTimes(1);
  });

  it("WEB_3b_backdrop_a_theme_change_builds_a_night_scene_once_and_day_comes_back_from_the_cache", () => {
    const { m } = mountShell(<CityBackdrop />);
    expect(sceneSpy).toHaveBeenCalledTimes(1);
    const dayEl = q(m.container, '[data-testid="fake-scene"]').getAttribute("data-build");
    act(() => seen.app.setPref("time", "night"));
    expect(sceneSpy).toHaveBeenCalledTimes(2);
    expect(sceneSpy).toHaveBeenLastCalledWith(expect.objectContaining({ night: true, still: true }));
    const nightEl = q(m.container, '[data-testid="fake-scene"]').getAttribute("data-build");
    expect(nightEl).not.toBe(dayEl);
    act(() => seen.app.setPref("time", "day"));
    expect(sceneSpy).toHaveBeenCalledTimes(2);
    expect(q(m.container, '[data-testid="fake-scene"]').getAttribute("data-build")).toBe(dayEl);
  });

  it("WEB_3b_backdrop_a_motion_change_is_a_new_key", () => {
    mountShell(<CityBackdrop />);
    act(() => seen.app.setPref("motion", "still"));
    expect(sceneSpy).toHaveBeenCalledTimes(2);
    act(() => seen.app.setPref("motion", "lively"));
    expect(sceneSpy).toHaveBeenCalledTimes(2);
  });

  it("WEB_3b_backdrop_an_unrelated_store_change_does_not_rebuild", () => {
    mountShell(<CityBackdrop />);
    act(() => seen.app.decide("depot"));
    act(() => seen.store.toggleMenu("notif"));
    act(() => seen.app.toast("hi"));
    expect(sceneSpy).toHaveBeenCalledTimes(1);
  });

  it("WEB_3b_backdrop_the_veil_covers_every_page_but_home", () => {
    for (const [path, veil] of [
      ["/park/home", 0],
      ["/park/worlds", 1],
      ["/park/world/k1", 1],
      ["/park/skills", 1],
      ["/park/ledger", 1],
      ["/park/agenda", 1],
      ["/park/team", 1],
      ["/park/profile", 1],
      ["/park/connectors", 1],
    ] as const) {
      const { m } = mountShell(<CityBackdrop />, { path });
      expect(qa(m.container, ".park-backdrop__veil"), path).toHaveLength(veil);
      m.unmount();
    }
  });

  it("WEB_3b_backdrop_feeds_the_pins_into_the_app", () => {
    mountShell(<CityBackdrop />, { viewport: { vw: 1440, vh: 900 } });
    expect(seen.app.pins).toEqual(scenePins(SCENE_SPOTS, 1440, 900));
    expect(seen.app.pins).toHaveLength(3);
    expect(seen.store.getState().pins).toEqual(seen.app.pins);
  });

  it("WEB_3b_backdrop_a_new_viewport_moves_the_pins_and_keeps_the_scene", () => {
    const { resize } = mountShell(<CityBackdrop />, { viewport: { vw: 1440, vh: 900 } });
    const first = seen.app.pins;
    resize(390, 844);
    expect(seen.app.pins).toEqual(scenePins(SCENE_SPOTS, 390, 844));
    expect(seen.app.pins).not.toEqual(first);
    expect(sceneSpy).toHaveBeenCalledTimes(1);
  });

  it("WEB_3b_backdrop_pins_come_from_the_cached_spots_of_the_current_theme", () => {
    mountShell(<CityBackdrop />);
    act(() => seen.app.setPref("time", "night"));
    expect(seen.app.pins).toEqual(scenePins(SCENE_SPOTS, 1440, 900));
  });
});
