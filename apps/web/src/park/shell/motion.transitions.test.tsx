// @vitest-environment happy-dom
// WEB-MOTION-2 (boot splash, page transitions, open-a-world steps), unit level. Pinned to
// design_handoff_tilo_web_app/README.md "Interactions and motion":
//   - Boot: the splash "fades over .45s" once the engines are ready, then it is gone (so it does not vanish in the
//     same tick the shell is ready);
//   - Open a world: steps every 340 ms (cities) / 250 ms (towns, villages), "the page swaps in at step 3; the card
//     fades out over 280 ms" (so the card is still there after the last step and goes after its fade);
//   - Reduced motion: "turns off all animation and transitions", and `motion: 'still'` is the person's own switch for
//     the same thing: the splash and the card then go at once (there is no fade to wait for).
// How the fade is waited out is not pinned: a timer on the real clock, a timer on the store's injected scheduler,
// or the browser's animationend / transitionend all pass (`drain` below runs all three). The durations themselves
// (450 ms, 280 ms) are measured on the running page in e2e/park-motion-transitions.spec.ts.
// The existing static-shell tests (WorldLoader.test.tsx "removed the moment ready turns true", "the card goes on
// the fourth tick"; AppShell.test.tsx "the card goes" after 250 ms) assert the opposite and are the builder's to edit.
import fc from "fast-check";
import { act, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { fakeScheduler } from "../../../test-support/park/appHarness";
import { cleanup, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp, mountShell, seen } from "../../../test-support/park/shellHarness";
import { BootSplash } from "./BootSplash";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

const realMatchMedia = window.matchMedia;
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: realMatchMedia,
  });
  window.history.pushState({}, "", "/");
});

/** The person (or the OS) asked for reduced motion: the media query answers yes. */
function reduceMotion(): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: /prefers-reduced-motion\s*:\s*reduce/.test(query),
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

type Sched = ReturnType<typeof fakeScheduler>;

/** The browser's own "the fade has finished" events, sent to every element on the page. */
function endEvents(): void {
  for (const el of [...document.body.querySelectorAll("*")]) {
    for (const [type, extra] of [
      ["transitionend", { propertyName: "opacity" }],
      ["animationend", { animationName: "fade" }],
    ] as const) {
      el.dispatchEvent(
        Object.assign(new Event(type, { bubbles: true }), { elapsedTime: 1, ...extra }),
      );
    }
  }
}

/** Waits out whatever the fade is waiting for: the real clock, the store's scheduler, the end events. */
function drain(sch?: Sched): void {
  for (let pass = 0; pass < 6; pass++) {
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    for (const t of sch?.live() ?? []) act(() => sch?.fire(t));
    act(() => endEvents());
  }
}

const splash = (): Element | null => document.querySelector('[aria-label="Loading Tilo"]');
const loaders = (): Element[] =>
  qa(document.body, '[role="status"]').filter((e) => (e.textContent ?? "").includes("OPENING"));
const loader = (): Element | null => loaders()[0] ?? null;
const open = (id: string) => act(() => seen.store.openWorld(id));
const tick = (sch: Sched, n = 1) => {
  for (let i = 0; i < n; i++) act(() => sch.fire(sch.live()[0]));
};

function Host({ onReady }: { onReady: (set: (v: boolean) => void) => void }) {
  const [ready, set] = useState(false);
  onReady(set);
  return <BootSplash ready={ready} />;
}

describe("WEB-MOTION-2 unit: the boot splash fades, then goes (README Boot: fades over .45s)", () => {
  it("WEB-MOTION-2 unit: the splash is still on screen when the shell turns ready (it is fading) and is gone once its fade has run", () => {
    vi.useFakeTimers();
    let setReady: (v: boolean) => void = () => undefined;
    const { sch } = mountShell(
      <Host
        onReady={(s) => {
          setReady = s;
        }}
      />,
    );
    expect(splash(), "the splash is up while the shell is not ready").not.toBeNull();
    expect(q(document.body, '[role="status"]').textContent).toContain("Loading your city");

    act(() => setReady(true));
    expect(splash(), "cut at once: there is no fade").not.toBeNull();
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(splash(), "gone before the .45 s fade could have finished").not.toBeNull();

    drain(sch);
    expect(splash(), "still there after its fade").toBeNull();
    expect(document.body.textContent).not.toContain("Loading your city");
  });

  it("FR_UX_12 WEB-MOTION-2 unit: with reduced motion the splash goes the moment the shell is ready (no fade to wait for)", () => {
    reduceMotion();
    let setReady: (v: boolean) => void = () => undefined;
    mountShell(
      <Host
        onReady={(s) => {
          setReady = s;
        }}
      />,
    );
    expect(splash()).not.toBeNull();
    act(() => setReady(true));
    expect(splash(), "reduced motion keeps the splash up for a fade that is turned off").toBeNull();
  });
});

describe("WEB-MOTION-2 unit: the world loader's card fades after the last step (README Open a world: fades out over 280 ms)", () => {
  it("WEB-MOTION-2 unit: the page swaps at step 3, the card is still there after step 4 (fading), then it goes", async () => {
    const { sch, navigate } = await mountApp();
    vi.useFakeTimers();
    open("comp");
    tick(sch, 2);
    expect(navigate).not.toHaveBeenCalled();
    tick(sch);
    expect(navigate).toHaveBeenCalledWith("/park/world/comp");
    expect(loader()).not.toBeNull();
    tick(sch); // step 4: the card starts to fade
    expect(loader(), "the card is cut instead of fading").not.toBeNull();
    drain(sch);
    expect(loader(), "the card never goes").toBeNull();
  });

  it("WEB-MOTION-2 unit: opening another world while a card is fading shows the new card at step 0, one card at a time, and it too goes", async () => {
    const { sch, navigate } = await mountApp();
    vi.useFakeTimers();
    open("k1");
    tick(sch, 4);
    expect(loader()).not.toBeNull();
    open("comp");
    expect(loaders()).toHaveLength(1);
    expect((loader() as Element).textContent).toContain("Competitor pricing");
    expect((loader() as Element).textContent).toContain("OPENING VILLAGE");
    tick(sch, 3);
    expect(navigate).toHaveBeenLastCalledWith("/park/world/comp");
    drain(sch);
    expect(loader()).toBeNull();
  });

  it("FR_UX_12 WEB-MOTION-2 unit: with reduced motion the card goes at the last step (nothing fades)", async () => {
    reduceMotion();
    const { sch } = await mountApp();
    open("comp");
    tick(sch, 3);
    expect(loader()).not.toBeNull();
    tick(sch);
    expect(loader(), "reduced motion keeps the card for a fade that is turned off").toBeNull();
  });

  it("FR_UX_12 WEB-MOTION-2 unit: with the 'still' motion preference the card goes at the last step too (README: motion 'still' freezes motion)", async () => {
    const { sch } = await mountApp();
    act(() => seen.app.setPref("motion", "still"));
    expect(seen.app.motion).toBe("still");
    open("comp");
    tick(sch, 3);
    expect(loader()).not.toBeNull();
    tick(sch);
    expect(loader(), "still keeps the card for a fade").toBeNull();
  });
});

describe("WEB-MOTION-2 property: opening worlds in any order never leaves two cards, and always ends with none", () => {
  it("WEB-MOTION-2 property: for any run of opens and steps, at most one loader card is on screen and draining leaves none", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(fc.constantFrom("k1", "comp", "invoice", "tick", "tick", "tick"), {
          maxLength: 14,
        }),
        async (ops) => {
          const { sch } = await mountApp();
          vi.useFakeTimers();
          try {
            for (const op of ops) {
              if (op === "tick") {
                const next = sch.live()[0];
                if (next) act(() => sch.fire(next));
              } else open(op);
              expect(loaders().length, `after ${op}`).toBeLessThanOrEqual(1);
            }
            drain(sch);
            expect(loaders(), `after ${ops.join(",")}`).toHaveLength(0);
          } finally {
            vi.useRealTimers();
            cleanup();
          }
        },
      ),
      { numRuns: 20, seed: 20261007 },
    );
  });
});
