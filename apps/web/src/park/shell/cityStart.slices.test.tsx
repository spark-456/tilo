// @vitest-environment happy-dom
// NFR-01 (ticket NFR-01-LANDING): the city is built in slices. After the start timer fires, the shell runs a few
// milliseconds of the build, then waits (`CITY_SLICE_MS`, through the injected scheduler) and goes on; nothing is
// shown until the scene is whole (the poster stays), and the scene is then drawn exactly once. The engine here
// takes 30 steps, and the clock moves 20 ms per reading, so every slice ends after one step.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../test-support/park/componentsHarness";
import { sceneSpy } from "../../../test-support/park/shellEngine";
import { mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { AppShell } from "./AppShell";
import { CITY_DEFER_MS, CITY_SLICE_MS } from "./cityStart";

const STEPS = 30;

vi.mock("../engines/park", async () => {
  const actual = await vi.importActual<typeof import("../engines/park")>("../engines/park");
  const { createElement } = await import("react");
  const { sceneSpy: spy } = await import("../../../test-support/park/shellEngine");
  return {
    ...actual,
    createPark: (...args: Parameters<typeof actual.createPark>) => ({
      ...actual.createPark(...args),
      scene: Object.assign((o?: unknown) => spy(o), {
        steps: (o?: unknown) =>
          (function* () {
            for (let i = 0; i < STEPS; i++) yield;
            return { ...spy(o), el: createElement("div", { "data-testid": "fake-scene" }) };
          })(),
      }),
    }),
  };
});

let clock = 0;
beforeEach(() => {
  clock = 0;
  vi.spyOn(performance, "now").mockImplementation(() => {
    clock += 20;
    return clock;
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
  window.history.pushState({}, "", "/");
});

describe("NFR_01_LANDING_slices: the city is built a slice at a time", () => {
  it("NFR_01_LANDING_slices_the_poster_stays_until_the_last_slice_and_the_scene_is_drawn_once", async () => {
    const { sch } = mountShell(
      <AppShell>
        <div />
      </AppShell>,
    );
    await settle();
    const start = sch.live().find((t) => t.ms === CITY_DEFER_MS);
    act(() => sch.fire(start));
    const slices = (): number => sch.timers.filter((t) => t.ms === CITY_SLICE_MS).length;
    // one slice has run, the next is waiting; nothing is shown yet
    expect(sch.live().filter((t) => t.ms === CITY_SLICE_MS)).toHaveLength(1);
    expect(document.querySelector('[data-testid="park-shell-poster"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="fake-scene"]')).toBeNull();
    let guard = 0;
    while (sch.live().some((t) => t.ms === CITY_SLICE_MS) && guard++ < 100) {
      expect(document.querySelector('[data-testid="fake-scene"]')).toBeNull();
      act(() => sch.fire(sch.live().find((t) => t.ms === CITY_SLICE_MS)));
    }
    // at least a dozen slices (not one big task), then the whole scene replaces the poster
    expect(slices()).toBeGreaterThanOrEqual(12);
    expect(document.querySelector('[data-testid="fake-scene"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="park-shell-poster"]')).toBeNull();
    expect(sceneSpy.mock.calls.length).toBe(1);
  });

  it("NFR_01_LANDING_slices_leaving_mid_build_cancels_the_pending_slice", async () => {
    const { m, sch } = mountShell(
      <AppShell>
        <div />
      </AppShell>,
    );
    await settle();
    // the first test cached the default city: ask for one nobody has drawn
    act(() => seen.app.setPref("motion", "still"));
    act(() => sch.fire(sch.live().find((t) => t.ms === CITY_DEFER_MS)));
    const pending = sch.live().find((t) => t.ms === CITY_SLICE_MS);
    expect(pending).toBeDefined();
    m.unmount();
    expect(pending?.cancelled).toBe(true);
  });
});
