// @vitest-environment happy-dom
// WEB-MOTION-1: how the shell chooses the city's motion (README "Interactions and motion": "Reduced motion:
// Turns off all animation and transitions. `motion: 'still'` also freezes the city"; handoff Tilo App.dc.html
// `renderVals`: still = motion === 'still', k = motion === 'calm' ? 1.9 : 1) and when it draws (README
// "City backdrop": "Draw it once and cache it per `time|motion`").
// Mounted through <AppShell/> with the scene engine replaced by a fast stand-in that writes the options each
// build was asked for on the scene element (test-support/park/motionEngine.ts). The tests read what is on
// screen, so they hold whatever an earlier test already put in the document-wide cache. What the browser
// then shows (cars moving, paused off Home, the budget) is in e2e/park-motion-backdrop.spec.ts.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q } from "../../../test-support/park/componentsHarness";
import { sceneSpy } from "../../../test-support/park/motionEngine";
import { mountApp, seen } from "../../../test-support/park/shellHarness";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/motionEngine")).parkMock(),
);

// A controllable prefers-reduced-motion. Any other media query does not match.
type Listener = (e: { matches: boolean; media: string }) => void;
let reduced = false;
const listeners = new Set<Listener>();
const REDUCE = "(prefers-reduced-motion: reduce)";
Object.defineProperty(window, "matchMedia", {
  configurable: true,
  writable: true,
  value: (query: string) => {
    const isMotion = /prefers-reduced-motion/.test(query);
    const noPref = /no-preference/.test(query);
    return {
      get matches() {
        if (!isMotion) return false;
        return noPref ? !reduced : reduced;
      },
      media: query,
      onchange: null,
      addEventListener: (_t: string, l: Listener) => {
        if (isMotion) listeners.add(l);
      },
      removeEventListener: (_t: string, l: Listener) => {
        listeners.delete(l);
      },
      addListener: (l: Listener) => {
        if (isMotion) listeners.add(l);
      },
      removeListener: (l: Listener) => {
        listeners.delete(l);
      },
      dispatchEvent: () => false,
    };
  },
});
function setReduced(value: boolean): void {
  reduced = value;
  act(() => {
    for (const l of [...listeners]) l({ matches: value, media: REDUCE });
  });
}

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  reduced = false;
  listeners.clear();
});

const scene = () => q(document.body, '[data-testid="fake-scene"]');
const build = () => scene().getAttribute("data-build");
const still = () => scene().getAttribute("data-still");
const k = () => Number(scene().getAttribute("data-k"));
const builds = () => sceneSpy.mock.calls.length;

describe("WEB-MOTION-1 motion preference: lively, calm, still", () => {
  it("WEB-MOTION-1 calm (the default, as in the handoff) shows a live city that is slower: not still, k = 1.9", async () => {
    await mountApp();
    expect(still()).toBe("false");
    expect(k()).toBeCloseTo(1.9, 5);
  });

  it("WEB-MOTION-1 lively shows the full, live city at full speed: not still, k = 1", async () => {
    await mountApp();
    await act(async () => seen.app.setPref("motion", "lively"));
    expect(still()).toBe("false");
    expect(k()).toBe(1);
  });

  it("WEB-MOTION-1 still shows a frozen city: still = true", async () => {
    await mountApp();
    expect(still(), "the live city it starts from is not frozen").toBe("false");
    await act(async () => seen.app.setPref("motion", "still"));
    expect(still()).toBe("true");
  });

  it("WEB-MOTION-1 every scene is the 1600 by 1000 picture whatever the motion", async () => {
    await mountApp();
    await act(async () => seen.app.setPref("motion", "calm"));
    await act(async () => seen.app.setPref("motion", "still"));
    expect(builds()).toBeGreaterThan(0);
    for (const c of sceneSpy.mock.calls) {
      expect(c[0]).toMatchObject({ w: 1600, h: 1000 });
    }
  });

  it("WEB-MOTION-1 night keeps the motion: a night city under calm is still live and slow", async () => {
    await mountApp();
    await act(async () => seen.app.setPref("time", "night"));
    await act(async () => seen.app.setPref("motion", "calm"));
    expect(scene().getAttribute("data-night")).toBe("true");
    expect(still()).toBe("false");
    expect(k()).toBeCloseTo(1.9, 5);
  });
});

describe("WEB-MOTION-1 the city holds still while the world loader is open (as the handoff does)", () => {
  it("WEB-MOTION-1 opening a world on Home pauses the city, and it is not paused before", async () => {
    await mountApp();
    const backdrop = () => q(document.body, ".park-shell__backdrop");
    expect(backdrop().hasAttribute("data-paused"), "Home, no loader: the city moves").toBe(false);
    await act(async () => seen.store.openWorld("k1"));
    expect(backdrop().hasAttribute("data-paused"), "the loader is open: the city holds").toBe(true);
  });
});

describe("WEB-MOTION-1 prefers-reduced-motion: a static frame, live while the page is open", () => {
  it("WEB-MOTION-1 reduced motion freezes the city even when the preference is lively, and lifting it brings the live city back from the cache", async () => {
    await mountApp();
    expect(still()).toBe("false");
    const live = build();

    await act(async () => setReduced(true));
    expect(still(), "the frame under reduced motion").toBe("true");
    expect(build()).not.toBe(live);

    const before = builds();
    await act(async () => setReduced(false));
    expect(still()).toBe("false");
    expect(build(), "the same live scene, from the cache").toBe(live);
    expect(builds()).toBe(before);
  });

  it("WEB-MOTION-1 a page that opens with reduced motion on never shows a moving city, whatever the preference", async () => {
    reduced = true;
    await mountApp();
    expect(still()).toBe("true");
    for (const motion of ["calm", "lively", "still"]) {
      await act(async () => seen.app.setPref("motion", motion));
      expect(still(), `motion ${motion} under reduced motion`).toBe("true");
    }
    await act(async () => seen.app.setPref("time", "night"));
    expect(still(), "night under reduced motion").toBe("true");
    // The control: lifting the setting gives the live city back, so the frames above were the setting's doing.
    await act(async () => seen.app.setPref("motion", "lively"));
    await act(async () => setReduced(false));
    expect(still()).toBe("false");
  });
});

describe("WEB-MOTION-1 cache: the city is drawn once per time|motion", () => {
  it("WEB-MOTION-1 changing page, hiding the tab and showing it again never redraw the city", async () => {
    await mountApp();
    const start = builds();
    const drawn = build();
    expect(still(), "the city drawn is the live one").toBe("false");
    const go = async (to: string) =>
      act(async () => {
        window.history.pushState({}, "", to);
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
    const setHidden = async (hidden: boolean) => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => (hidden ? "hidden" : "visible"),
      });
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
    };
    await go("/park/ledger");
    await go("/park/agenda");
    await go("/park/home");
    await setHidden(true);
    await setHidden(false);
    expect(builds()).toBe(start);
    expect(build()).toBe(drawn);
  });

  it("WEB-MOTION-1 each motion has its own key: going calm, still and back reuses what was drawn", async () => {
    await mountApp();
    await act(async () => seen.app.setPref("time", "night"));
    await act(async () => seen.app.setPref("motion", "calm"));
    const calm = build();
    expect(still(), "calm is live").toBe("false");
    await act(async () => seen.app.setPref("motion", "still"));
    const frozen = build();
    expect(new Set([calm, frozen]).size).toBe(2);
    const before = builds();
    await act(async () => seen.app.setPref("motion", "calm"));
    expect(build()).toBe(calm);
    await act(async () => seen.app.setPref("motion", "still"));
    expect(build()).toBe(frozen);
    expect(builds()).toBe(before);
  });
});
