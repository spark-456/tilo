// @vitest-environment happy-dom
// WEB-MOTION-2 fix pass (security and honesty follow-ups), unit level:
//   - the splash and the world card never depend on animationend alone: where the browser runs CSS animations, the
//     injected scheduler removes them a little after the fade should have ended, and the browser's own animationend
//     cancels that timer (the DOM stand-in has no CSSAnimation, so the other unit tests see no extra timer);
//   - the page-change bar reads no progress it did not measure: the timers cap it at 78 and 100 comes only in the
//     commit that puts the new page on screen (docs/open-questions.md BQ-WEB-MOTION-2).
import { Suspense, act, useLayoutEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp, mountShell, seen } from "../../../test-support/park/shellHarness";
import { BootSplash } from "./BootSplash";
import { CAP_PCT, usePageSwap } from "./motion";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

const g = globalThis as unknown as { CSSAnimation?: unknown };
let hadCssAnimation = false;
beforeEach(() => {
  hadCssAnimation = "CSSAnimation" in g;
});
afterEach(() => {
  if (!hadCssAnimation) Reflect.deleteProperty(g, "CSSAnimation");
  cleanup();
  window.history.pushState({}, "", "/");
});
/** This browser runs CSS animations (the DOM stand-in does not). */
const browserWithAnimations = () => {
  g.CSSAnimation = class {};
};

const splash = (): Element | null => document.querySelector('[aria-label="Loading Tilo"]');
const card = (): Element | undefined =>
  qa(document.body, '[role="status"]').find((e) => (e.textContent ?? "").includes("OPENING"));
const animationEnd = (el: Element | null | undefined) =>
  act(() => {
    el?.dispatchEvent(new Event("animationend", { bubbles: true }));
  });

function SplashHost({ onReady }: { onReady: (set: (v: boolean) => void) => void }) {
  const [ready, set] = useState(false);
  onReady(set);
  return <BootSplash ready={ready} />;
}
function splashFading() {
  let setReady: (v: boolean) => void = () => undefined;
  const r = mountShell(
    <SplashHost
      onReady={(s) => {
        setReady = s;
      }}
    />,
  );
  act(() => setReady(true));
  return r;
}

describe("WEB-MOTION-2 guards: the fades do not wait on animationend alone", () => {
  it("WEB-MOTION-2 guards: where animations run, a fading splash is also removed by the scheduler at 450 ms plus a margin", () => {
    browserWithAnimations();
    const { sch } = splashFading();
    expect(splash()).not.toBeNull();
    const timer = sch.live().at(-1);
    expect(timer?.ms).toBeGreaterThan(450);
    expect(timer?.ms).toBeLessThanOrEqual(450 + 250);
    act(() => sch.fire(timer));
    expect(splash()).toBeNull();
  });

  it("WEB-MOTION-2 guards: the splash's animationend comes first and cancels the fallback timer", () => {
    browserWithAnimations();
    const { sch } = splashFading();
    expect(sch.live()).toHaveLength(1);
    animationEnd(splash());
    expect(splash()).toBeNull();
    expect(sch.live()).toHaveLength(0);
  });

  it("WEB-MOTION-2 guards: where animations run, a fading world card is also removed by the scheduler at 280 ms plus a margin", async () => {
    const { sch } = await mountApp();
    browserWithAnimations(); // after the splash has gone through its own fade
    act(() => seen.store.openWorld("comp"));
    for (let i = 0; i < 4; i++) act(() => sch.fire(sch.live()[0]));
    expect(card()).toBeDefined();
    const timer = sch.live().at(-1);
    expect(timer?.ms).toBeGreaterThan(280);
    expect(timer?.ms).toBeLessThanOrEqual(280 + 250);
    act(() => sch.fire(timer));
    expect(card()).toBeUndefined();
  });

  it("WEB-MOTION-2 guards: the card's animationend comes first and cancels the fallback timer", async () => {
    const { sch } = await mountApp();
    browserWithAnimations();
    act(() => seen.store.openWorld("comp"));
    for (let i = 0; i < 4; i++) act(() => sch.fire(sch.live()[0]));
    const before = sch.live().length;
    expect(before).toBeGreaterThan(0);
    animationEnd(card());
    expect(card()).toBeUndefined();
    expect(sch.live()).toHaveLength(0);
  });

  it("WEB-MOTION-2 guards: without CSS animations (the DOM stand-in) the fades arm no timer of their own", async () => {
    const { sch } = splashFading();
    expect(sch.live()).toHaveLength(0);
    animationEnd(splash());
    expect(splash()).toBeNull();
  });
});

describe("WEB-MOTION-2 guards: the page-change bar never claims progress it did not measure", () => {
  let release: () => void = () => undefined;
  let gate: Promise<void> = Promise.resolve();
  /** The new page does not render until `release()`: a heavy or late page. */
  function Gate({ k }: { k: string }) {
    if (k === "b" && !released) throw gate;
    return <div data-testid="page">{k}</div>;
  }
  let released = false;
  const frames: { pct: number; shown: string; want: string; phase: string }[] = [];
  let setKey: (k: string) => void = () => undefined;

  function Swap() {
    const [k, set] = useState("a");
    setKey = set;
    const s = usePageSwap(
      <Suspense fallback={null}>
        <Gate k={k} />
      </Suspense>,
      k,
      "animate",
    );
    // What was committed (not what a discarded render tried): effects run only for a commit.
    useLayoutEffect(() => {
      frames.push({ pct: s.bar.pct, shown: s.key, want: k, phase: s.phase });
    });
    return <div data-testid="out">{s.node}</div>;
  }

  it("WEB-MOTION-2 guards: the timers stop at 78 and 100 comes only in the commit that shows the new page", async () => {
    released = false;
    gate = new Promise<void>((done) => {
      release = () => {
        released = true;
        done();
      };
    });
    frames.length = 0;
    const { sch } = mountShell(<Swap />);
    act(() => setKey("b"));
    expect(frames.at(-1)).toMatchObject({ pct: 35, phase: "out" });

    // The out timer fires: the bar goes to the cap and the new page starts to render, but it is not ready.
    act(() => sch.fire(sch.live()[0]));
    for (const t of sch.live()) act(() => sch.fire(t)); // every other timer too: none may say 100
    expect(frames.at(-1)?.pct).toBe(CAP_PCT);
    expect(frames.at(-1)?.shown).toBe("a");
    expect(frames.some((f) => f.pct === 100)).toBe(false);

    // The page is ready and commits: now, and only now, the bar reads 100.
    await act(async () => {
      release();
      await gate;
    });
    expect(q(document.body, '[data-testid="page"]').textContent).toBe("b");
    expect(frames.at(-1)?.pct).toBe(100);
    for (const f of frames) {
      if (f.pct === 100) expect(f.shown, "100 with the old page still on screen").toBe(f.want);
    }
  });
});
