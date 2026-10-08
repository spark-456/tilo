// @vitest-environment happy-dom
// FR-UX-12 / issue #588 follow-up (flaky e2e "the splash was cut before its fade ran"): the e2e probe wrote down
// WHEN IT NOTICED an animation, which a busy main thread (the first city draw) delays by tens of ms, so the
// splash's fade looked shorter than .45 s. Each record now also carries the animation's own startTime, which no
// main-thread delay can move. The probe runs in the page; here it runs against a stand-in document.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ProbeData, installProbe } from "../../../e2e/support/motionProbe";

interface FakeAnim {
  startTime: number | null;
  playState: string;
  effect: unknown;
}
let clock = 0;
let live: FakeAnim[] = [];

const fadeOn = (target: Element, startTime: number | null): FakeAnim => ({
  startTime,
  playState: "running",
  effect: {
    target,
    getKeyframes: () => [
      { offset: 0, opacity: "1", easing: "ease" },
      { offset: 1, opacity: "0" },
    ],
    getTiming: () => ({ duration: 450, delay: 0, iterations: 1, easing: "linear" }),
  },
});
const probe = () =>
  (window as unknown as { __probe: { start(): void; data(): ProbeData } }).__probe;
const tick = (): void => {
  vi.advanceTimersByTime(4);
};

beforeEach(() => {
  vi.useFakeTimers();
  clock = 0;
  live = [];
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  (document as unknown as { getAnimations: () => FakeAnim[] }).getAnimations = () => live;
  (window as unknown as { __probe?: unknown }).__probe = undefined;
  installProbe();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("FR-UX-12 probe: a record carries when the animation began, not when the probe noticed it", () => {
  it("FR-UX-12 probe: a fade noticed 400 ms late still reports the start the browser gave it", () => {
    const el = document.createElement("div");
    document.body.append(el);
    clock = 1000;
    probe().start();
    clock = 1400; // the main thread was busy: the probe's next look is 400 ms after the fade began
    live.push(fadeOn(el, 1010));
    tick();
    const rec = probe().data().recs[0];
    expect(rec, "the fade is recorded").toBeDefined();
    expect(rec?.t, "noticed at").toBeCloseTo(400, 0);
    expect(rec?.start, "began at").toBeCloseTo(10, 0);
  });

  it("FR-UX-12 probe: an animation with no startTime yet gets it on a later look", () => {
    const el = document.createElement("div");
    document.body.append(el);
    probe().start();
    const a = fadeOn(el, null);
    live.push(a);
    clock = 50;
    tick();
    expect(probe().data().recs[0]?.start, "falls back to the noticed time at first").toBe(50);
    a.startTime = 62;
    clock = 80;
    tick();
    expect(probe().data().recs[0]?.start).toBeCloseTo(62, 0);
  });

  it("FR-UX-12 probe: start() makes both clocks count from that moment", () => {
    const el = document.createElement("div");
    document.body.append(el);
    clock = 300;
    probe().start();
    live.push(fadeOn(el, 300));
    clock = 304;
    tick();
    const rec = probe().data().recs[0];
    expect(rec?.start).toBeCloseTo(0, 0);
    expect(rec?.t).toBeCloseTo(4, 0);
  });
});
