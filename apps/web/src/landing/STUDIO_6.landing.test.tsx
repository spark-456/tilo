// @vitest-environment happy-dom
// STUDIO-6: the signed-out landing in Studio. "Continue with Google" stays the one filled button; the central stage is a
// replay of a recorded run, labelled so on every frame, one recorded event per step, and still with reduced motion;
// the art engines stay off the sign-in bundle (NFR-01).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../../test-support/park/componentsHarness";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { SignInScreen } from "../auth/SignInScreen";
import LandingStage, { STEP_MS } from "./LandingStage";
import { RECORDED_RUN, foldRun } from "./recordedRun";

const media = (reduce: boolean) => (query: string) =>
  ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;

let restore: (() => void) | null = null;
const prefer = (reduce: boolean) => {
  const before = window.matchMedia;
  window.matchMedia = media(reduce);
  restore = () => {
    window.matchMedia = before;
  };
};

beforeEach(() => prefer(false));
afterEach(() => {
  cleanup();
  restore?.();
  vi.useRealTimers();
});

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};
const buttons = () => qa<HTMLButtonElement>(document.body, "button");
const named = (name: string) => buttons().filter((b) => (b.textContent ?? "").trim() === name);
const stage = () => q<HTMLElement>(document.body, '[data-testid="landing-stage"]');
const last = EVENTS_VILLAGE_BASIC.length;

const landing = () =>
  mount(
    <SignInScreen
      busy={false}
      failed={false}
      failedText="Failed."
      onGoogle={() => undefined}
      onDemo={() => undefined}
    />,
  );

describe("STUDIO_6 the signed-out landing", () => {
  it("STUDIO_6 Continue with Google is on the page, once, and is the only filled button", async () => {
    landing();
    expect(named("Continue with Google")).toHaveLength(1);
    expect(named("Explore a demo session")).toHaveLength(1);
    await settle();
    expect(stage()).not.toBeNull(); // the landing below the hero arrived
    expect(named("Continue with Google")).toHaveLength(1);
    expect(qa(document.body, ".landing-btn--primary")).toHaveLength(1);
    expect(qa(document.body, "input, textarea, form")).toHaveLength(0);
  });

  it("STUDIO_6 the stage carries the recorded-example label and says nothing is live", async () => {
    landing();
    await settle();
    const label = q<HTMLElement>(stage(), "figcaption");
    expect(label.textContent).toContain("Recorded example");
    expect(label.textContent).toContain("Nothing here is live.");
    expect(stage().getAttribute("aria-labelledby")).toBe(label.id);
  });

  it("STUDIO_6 with reduced motion the stage is the record's last frame, still, with no play control", () => {
    prefer(true);
    vi.useFakeTimers();
    mount(<LandingStage night={false} />);
    expect(stage().dataset.static).toBe("true");
    expect(stage().dataset.step).toBe(String(last));
    expect(q(document.body, '[data-testid="landing-stage-done"]')?.textContent).toContain(
      RECORDED_RUN.facts.done as string,
    );
    expect(named("Pause replay")).toHaveLength(0);
    act(() => {
      vi.advanceTimersByTime(STEP_MS * 10);
    });
    expect(stage().dataset.step).toBe(String(last));
  });

  it("STUDIO_6 the replay moves one recorded event per step, can pause, and stops at the end", () => {
    vi.useFakeTimers();
    mount(<LandingStage night={false} />);
    expect(stage().dataset.step).toBe("1");
    act(() => {
      vi.advanceTimersByTime(STEP_MS);
    });
    expect(stage().dataset.step).toBe("2");
    act(() => named("Pause replay")[0]?.click());
    act(() => {
      vi.advanceTimersByTime(STEP_MS * 5);
    });
    expect(stage().dataset.step).toBe("2");
    act(() => named("Play replay")[0]?.click());
    for (let i = 0; i < last; i += 1) {
      act(() => {
        vi.advanceTimersByTime(STEP_MS);
      });
    }
    expect(stage().dataset.step).toBe(String(last));
    expect(named("Replay again")).toHaveLength(1);
  });
});

describe("STUDIO_6 the recorded run", () => {
  it("STUDIO_6 folding is pure and every word on the stage is a recorded summary", () => {
    const a = foldRun(EVENTS_VILLAGE_BASIC, LAYOUT_VILLAGE_BASIC);
    const b = foldRun(EVENTS_VILLAGE_BASIC, LAYOUT_VILLAGE_BASIC);
    expect(JSON.stringify(a.frames)).toBe(JSON.stringify(b.frames));
    expect(a.frames).toHaveLength(last + 1);
    const summaries = new Set(EVENTS_VILLAGE_BASIC.map((e) => e.summary));
    for (const frame of a.frames)
      for (const line of frame.lines) expect(summaries).toContain(line.text);
    expect(a.frames[0]?.plan).toBeNull();
    const firstBuilding = EVENTS_VILLAGE_BASIC.findIndex((e) => e.type === "building.planned");
    expect(a.frames[firstBuilding]?.plan).toBeNull();
    expect(a.frames[firstBuilding + 1]?.plan?.districts[0]?.buildings).toHaveLength(1);
    expect(a.frames[last]?.done).toBe(EVENTS_VILLAGE_BASIC[last - 1]?.summary);
  });
});

describe("STUDIO_6 NFR-01 the sign-in bundle", () => {
  it("STUDIO_6 the hero loads the landing art lazily and never pixi or the world engine", () => {
    const src = readFileSync(join(__dirname, "..", "auth", "SignInScreen.tsx"), "utf8");
    const statics = [...src.matchAll(/^import[^;]*?from\s+"([^"]+)"/gm)].map((m) => m[1]);
    expect(
      statics.some((s) => /landingKit|LandingBody|LandingStage|engines|pixi|world\//.test(s ?? "")),
    ).toBe(false);
    expect(src).toContain('lazy(() => import("../landing/LandingBody"))');
  });
});
