// @vitest-environment happy-dom
// FR-SET-03 (docs/prd-supplement-design-2026-10-06.md §1.5):
// "Appearance. Day or night, and motion: lively, calm or still. 'Still' freezes the city;
// reduced-motion settings are always respected."
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../test-support/park/componentsHarness";
import { ParkApp } from "../app/ParkApp";
import { useAppearance } from "./cityMotion";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/motionEngine")).parkMock(),
);

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

async function setReduced(value: boolean): Promise<void> {
  reduced = value;
  await act(async () => {
    for (const l of [...listeners]) l({ matches: value, media: REDUCE });
  });
}

const tap = async (el: Element): Promise<void> => {
  await act(async () => {
    click(el);
  });
};

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
  await act(async () => undefined);
};

const visitAppearance = async () => {
  window.history.pushState({}, "", "/park/profile?tab=appearance");
  const m = mount(<ParkApp />);
  await settle();
  return m;
};

const scene = () => q(document.body, '[data-testid="fake-scene"]');
const buttonNamed = (root: ParentNode, label: string): HTMLButtonElement => {
  const found = qa<HTMLButtonElement>(root, "button").find(
    (b) => (b.textContent ?? "").trim() === label,
  );
  if (!found) throw new Error(`no button named ${label}`);
  return found;
};
const buttonContaining = (root: ParentNode, sub: string): HTMLButtonElement => {
  const found = qa<HTMLButtonElement>(root, "button").find((b) =>
    (b.textContent ?? "").includes(sub),
  );
  if (!found) throw new Error(`no button containing ${sub}`);
  return found;
};

beforeEach(() => {
  window.localStorage.clear();
  reduced = false;
  listeners.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  reduced = false;
  listeners.clear();
});

describe("FR_SET_03: Appearance settings (day/night, lively/calm/still, reduced-motion, persistence)", () => {
  it("test_FR_SET_03_day_and_night_switches_theme_tokens_and_persists_in_localStorage_with_try_catch", async () => {
    expect(typeof useAppearance).toBe("function");
    const m = await visitAppearance();
    const root = () => q(m.container, "[data-park]");
    expect(root().getAttribute("data-time")).toBe("day");
    expect(scene().getAttribute("data-night")).toBe("false");

    // Switch to Night via Profile > Appearance
    await tap(buttonContaining(m.container, "Lamps and glow"));
    expect(root().getAttribute("data-time")).toBe("night");
    expect(scene().getAttribute("data-night")).toBe("true");
    expect(buttonContaining(m.container, "Lamps and glow").getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(window.localStorage.getItem("tilo.time")).toBe("night");

    // Switch back to Day via Profile > Appearance
    await tap(buttonContaining(m.container, "Bright lawns"));
    expect(root().getAttribute("data-time")).toBe("day");
    expect(scene().getAttribute("data-night")).toBe("false");
    expect(window.localStorage.getItem("tilo.time")).toBe("day");

    // When localStorage throws (private mode), switching still works in-memory without throwing
    const origSet = window.localStorage.setItem.bind(window.localStorage);
    window.localStorage.setItem = () => {
      throw new Error("QuotaExceededError");
    };
    try {
      await tap(buttonContaining(m.container, "Lamps and glow"));
      expect(root().getAttribute("data-time")).toBe("night");
      await tap(buttonNamed(m.container, "Still"));
      expect(scene().getAttribute("data-still")).toBe("true");
    } finally {
      window.localStorage.setItem = origSet;
    }
  });

  it("test_FR_SET_03_still_stops_all_ambient_city_motion_and_calm_lowers_it", async () => {
    const m = await visitAppearance();
    // Default is calm: live city, lowered speed (k = 1.9)
    expect(scene().getAttribute("data-still")).toBe("false");
    expect(Number(scene().getAttribute("data-k"))).toBeCloseTo(1.9, 5);

    // Lively: full speed (k = 1, still = false)
    await tap(buttonNamed(m.container, "Lively"));
    expect(scene().getAttribute("data-still")).toBe("false");
    expect(Number(scene().getAttribute("data-k"))).toBe(1);
    expect(window.localStorage.getItem("tilo.motion")).toBe("lively");

    // Calm: lowered speed (k = 1.9, still = false)
    await tap(buttonNamed(m.container, "Calm"));
    expect(scene().getAttribute("data-still")).toBe("false");
    expect(Number(scene().getAttribute("data-k"))).toBeCloseTo(1.9, 5);
    expect(window.localStorage.getItem("tilo.motion")).toBe("calm");

    // Still: freezes the city completely (still = true)
    await tap(buttonNamed(m.container, "Still"));
    expect(scene().getAttribute("data-still")).toBe("true");
    expect(buttonNamed(m.container, "Still").getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem("tilo.motion")).toBe("still");
  });

  it("test_FR_SET_03_prefers_reduced_motion_forces_still_whatever_the_setting_says", async () => {
    const m = await visitAppearance();
    await tap(buttonNamed(m.container, "Lively"));
    expect(scene().getAttribute("data-still")).toBe("false");

    await setReduced(true);
    expect(scene().getAttribute("data-still")).toBe("true");

    await tap(buttonNamed(m.container, "Calm"));
    expect(scene().getAttribute("data-still")).toBe("true");

    await tap(buttonNamed(m.container, "Lively"));
    expect(scene().getAttribute("data-still")).toBe("true");

    await setReduced(false);
    expect(scene().getAttribute("data-still")).toBe("false");
  });

  it("test_FR_SET_03_choice_survives_a_reload", async () => {
    const first = await visitAppearance();
    await tap(buttonContaining(first.container, "Lamps and glow"));
    await tap(buttonNamed(first.container, "Still"));
    expect(window.localStorage.getItem("tilo.time")).toBe("night");
    expect(window.localStorage.getItem("tilo.motion")).toBe("still");

    // Simulate reload: unmount the first app tree without clearing localStorage, then mount a fresh ParkApp
    first.unmount();
    const reloaded = await visitAppearance();
    expect(q(reloaded.container, "[data-park]").getAttribute("data-time")).toBe("night");
    expect(scene().getAttribute("data-night")).toBe("true");
    expect(scene().getAttribute("data-still")).toBe("true");
    expect(
      buttonContaining(reloaded.container, "Lamps and glow").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(buttonNamed(reloaded.container, "Still").getAttribute("aria-pressed")).toBe("true");
  });
});
