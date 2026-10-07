// @vitest-environment happy-dom
// NFR-01 (PRD 17.1): landing page to interactive <= 2.0 s desktop, <= 3.5 s on a mid-range phone on 4G. The city
// backdrop (about nine full-size pictures and 130 cars and walkers, each its own SVG) is what a phone cannot
// afford before the first character can be typed, so the shell paints its page first and draws the city
// afterwards (the supervisor's ruling for ticket NFR-01-LANDING):
//   - the first commit of the shell does no scene work: scene() is not called and no city is mounted;
//   - until then a poster holds the backdrop's place (a plain fixed box inside the same layer, so the city
//     arriving shifts nothing);
//   - the city is requested once the page is up, through the injected scheduler (the shell's only sanctioned
//     timer): `CITY_DEFER_MS` after the shell is ready, never on the first render;
//   - when it fires the scene is drawn once and the pins reach app.pins; after that a theme or motion change
//     draws the new scene at once (no second wait);
//   - leaving before it fires cancels it.
// Pinned surface: park/shell/cityStart.ts exports `CITY_DEFER_MS` (a number of ms, 1 to 5000). The poster is
// `[data-testid="park-shell-poster"]` inside the `.park-shell__backdrop` layer.
// The scene cache is module-level, so the deferral is pinned by the FIRST test of this file (nothing cached).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { sceneConfig, sceneSpy } from "../../../test-support/park/shellEngine";
import { mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { AppShell } from "./AppShell";
import { CITY_DEFER_MS } from "./cityStart";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  sceneConfig.spots = [];
});

const shell = () =>
  mountShell(
    <AppShell>
      <div data-testid="kid">page</div>
    </AppShell>,
  );
const cityTimer = (sch: ReturnType<typeof mountShell>["sch"]) =>
  sch.live().filter((t) => t.ms === CITY_DEFER_MS);
const fakeScene = () => document.querySelector('[data-testid="fake-scene"]');
const poster = () => document.querySelector('[data-testid="park-shell-poster"]');

describe("NFR_01_LANDING_shell: the page first, the city after", () => {
  it("NFR_01_LANDING_first_render_paints_the_page_with_no_scene_work_and_a_poster_in_the_backdrop", async () => {
    sceneConfig.spots = [
      { x: 1000, y: 420, area: 4, st: "s" },
      { x: 820, y: 640, area: 4, st: "s" },
      { x: 900, y: 250, area: 2, st: "s" },
    ];
    const { m, sch } = shell();
    await settle();
    // the page is there: the nav, the one main with the page, and the splash has gone (fonts settled)
    expect(qa(m.container, "header nav[aria-label]")).toHaveLength(1);
    expect(q(m.container, "main").contains(q(m.container, '[data-testid="kid"]'))).toBe(true);
    // no scene work yet, and no city mounted
    expect(sceneSpy).not.toHaveBeenCalled();
    expect(fakeScene()).toBeNull();
    expect(seen.app.pins).toEqual([]);
    // the poster stands in the backdrop layer, which is aria-hidden and holds nothing to click
    const layer = q(m.container, ".park-shell__backdrop");
    expect(layer.getAttribute("aria-hidden")).toBe("true");
    expect(layer.contains(poster())).toBe(true);
    expect(poster()?.textContent).toBe("");
    expect(poster()?.querySelector("a, button, input, [tabindex]")).toBeNull();
    // the city is asked for through the scheduler, once, and only after the shell is ready
    expect(cityTimer(sch)).toHaveLength(1);
  });

  it("NFR_01_LANDING_the_city_is_drawn_once_when_the_timer_fires_and_the_pins_follow", async () => {
    sceneConfig.spots = [
      { x: 1000, y: 420, area: 4, st: "s" },
      { x: 820, y: 640, area: 4, st: "s" },
      { x: 900, y: 250, area: 2, st: "s" },
    ];
    const { m, sch } = shell();
    await settle();
    const [timer] = cityTimer(sch);
    expect(timer).toBeDefined();
    const before = sceneSpy.mock.calls.length;
    act(() => sch.fire(timer));
    expect(sceneSpy.mock.calls.length - before).toBeLessThanOrEqual(1);
    expect(qa(m.container, '[data-testid="fake-scene"]')).toHaveLength(1);
    expect(q(m.container, ".park-shell__backdrop").contains(fakeScene())).toBe(true);
    expect(poster()).toBeNull(); // the city has replaced the poster, in the same place
    expect(seen.app.pins).toHaveLength(3);
    // the page did not remount: the same main still holds the page
    expect(q(m.container, "main").contains(q(m.container, '[data-testid="kid"]'))).toBe(true);
  });

  it("NFR_01_LANDING_after_the_city_has_started_a_theme_change_draws_the_new_scene_at_once", async () => {
    const { m, sch } = shell();
    await settle();
    act(() => sch.fire(cityTimer(sch)[0]));
    expect(fakeScene()?.getAttribute("data-night")).toBe("false");
    const waiting = sch.schedule.mock.calls.filter((c) => c[1] === CITY_DEFER_MS).length;
    click(q(m.container, 'button[aria-label="Switch to night"]'));
    expect(fakeScene()?.getAttribute("data-night")).toBe("true");
    expect(poster()).toBeNull();
    // no second wait for the second key
    expect(sch.schedule.mock.calls.filter((c) => c[1] === CITY_DEFER_MS).length).toBe(waiting);
  });

  it("NFR_01_LANDING_a_theme_change_before_the_city_starts_waits_for_the_same_timer", async () => {
    const { m, sch } = shell();
    await settle();
    const drawn = sceneSpy.mock.calls.length;
    click(q(m.container, 'button[aria-label="Switch to night"]'));
    expect(sceneSpy.mock.calls.length).toBe(drawn);
    expect(fakeScene()).toBeNull();
    expect(poster()).not.toBeNull();
    act(() => sch.fire(cityTimer(sch).at(-1)));
    expect(fakeScene()?.getAttribute("data-night")).toBe("true");
  });

  it("NFR_01_LANDING_leaving_before_the_timer_fires_cancels_it", async () => {
    const { m, sch } = shell();
    await settle();
    const [timer] = cityTimer(sch);
    const drawn = sceneSpy.mock.calls.length;
    m.unmount();
    expect(timer?.cancelled).toBe(true);
    act(() => sch.fire(timer));
    expect(sceneSpy.mock.calls.length).toBe(drawn);
  });
});
