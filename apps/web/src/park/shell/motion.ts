// The shell's chrome motion, driven by state (WEB-MOTION-2; README "Interactions and motion": Page change, Open a
// world, Boot; PRD 9.4: it moves only because a person acted, never because of an agent). Three hooks, no timer of
// their own: the page swap waits on the provider's injected scheduler, and the two fades (the boot splash, the world
// card) wait for the browser's own animationend, with the scheduler as a fallback. The CSS that moves things is park.shell.css; this file only decides
// which state the markup is in. Reduced motion and the 'still' preference skip every wait: things change at once.
import {
  type ReactNode,
  startTransition,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useParkStore, useSchedule } from "../app/context";
import type { WorldLaunch } from "../app/store";

const REDUCE = "(prefers-reduced-motion: reduce)";
const subscribeReduced = (on: () => void): (() => void) => {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const list = window.matchMedia(REDUCE);
  list.addEventListener("change", on);
  return () => list.removeEventListener("change", on);
};
const reducedNow = (): boolean =>
  typeof window.matchMedia === "function" && window.matchMedia(REDUCE).matches;

/** True when the OS asks for reduced motion or the person chose 'still' (Profile > Appearance). */
export function useMotionOff(): boolean {
  const store = useParkStore();
  const reduced = useSyncExternalStore(subscribeReduced, reducedNow);
  const still = useSyncExternalStore(store.subscribe, () => store.getState().motion === "still");
  return reduced || still;
}

/** The top progress bar: whether it shows and how full it is (0 to 100). */
export interface Bar {
  on: boolean;
  pct: number;
}
export const NO_BAR: Bar = { on: false, pct: 0 };

type Phase = "in" | "out" | "pre" | "hold" | "wait";
/** How a change of page is shown: faded (a tab click), after a short wait with no motion (a tab click under
 * reduced motion), or at once (the browser's back button, a link in a page, a world card covering it). */
export type SwapMode = "animate" | "wait" | "now";
/** README: the old page goes out for 200 ms, the new one starts 40 ms after the swap, the bar hides 460 ms and
 * resets 820 ms after the swap. */
const OUT_MS = 200;
/** The most the bar reads from timers alone; 100 comes only from the new page's commit. */
export const CAP_PCT = 78;
const IN_MS = 40;
const HIDE_MS = 420;
const RESET_MS = 1000;

export interface PageSwap {
  /** What the page outlet draws: the page the person left while it fades out, else the live page. */
  node: ReactNode;
  /** The key of the page on screen. */
  key: string;
  /** "in" is the settled state; "out", "pre" and "hold" are the stages of a swap (a data attribute on <main>). */
  phase: Phase;
  bar: Bar;
  /** The bar's opacity transition has ended: if it was fading out, it is emptied now. */
  barFaded: () => void;
}

/**
 * A change of `key` fades the old page out, swaps, scrolls to the top and fades the new one in, with the bar
 * stepping 35, 78, 100 (mode "animate"); see SwapMode for the others.
 */
export function usePageSwap(children: ReactNode, key: string, mode: SwapMode): PageSwap {
  const schedule = useSchedule();
  const [shown, setShown] = useState(key);
  const [phase, setPhase] = useState<Phase>("in");
  const [bar, setBar] = useState<Bar>(NO_BAR);
  const held = useRef(children);
  const latest = useRef(key);
  latest.current = key;
  if (key === shown) held.current = children;
  else if (phase === "out" || phase === "wait") {
    // Already going out: the timer below swaps to whichever page is asked for last.
  } else if (mode === "wait") {
    setPhase("wait");
  } else if (mode === "now") {
    setShown(key);
    // Home and the other pages sit in different boxes: showing the swap in one frame would count as a layout
    // shift, so the new page stays out of sight for the 40 ms the animated swap also waits.
    setPhase((key === "home") !== (shown === "home") ? "hold" : "in");
    setBar(NO_BAR);
  } else {
    setPhase("out");
    setBar({ on: true, pct: 35 });
  }
  useEffect(() => {
    if (phase === "out") {
      // A transition: the new page renders in slices while the old one is still out of sight, so a heavy page
      // never holds the main thread for long.
      // The bar is held at CAP_PCT until then: the timers never say 100, only the commit below does.
      return schedule(() => {
        setBar({ on: true, pct: CAP_PCT });
        startTransition(() => {
          setShown(latest.current);
          setPhase("pre");
        });
      }, OUT_MS);
    }
    if (phase === "pre") {
      return schedule(() => setPhase("in"), IN_MS);
    }
    if (phase === "wait") {
      return schedule(() => {
        setShown(latest.current);
        setPhase("hold");
      }, IN_MS);
    }
    if (phase === "hold") return schedule(() => setPhase("in"), IN_MS);
    return undefined;
  }, [phase, schedule]);
  // In the commit that puts the new page on screen, so the scroll and the swap are one step. This commit is the one
  // real event of the change: the bar reads 100 here and never earlier (it shows no progress it did not measure).
  useLayoutEffect(() => {
    if (phase !== "pre") return;
    window.scrollTo(0, 0);
    setBar({ on: true, pct: 100 });
  }, [phase]);
  useEffect(() => {
    if (phase !== "in" || bar.pct !== 100 || !bar.on) return undefined;
    return schedule(() => setBar({ on: false, pct: 100 }), HIDE_MS);
  }, [phase, bar, schedule]);
  // Back to empty only once the bar has faded out (the browser's transitionend, `barFaded`), never on a clock
  // alone: a busy main thread must not empty a bar that is still in view. The scheduler is the fallback.
  const faded = !bar.on && bar.pct === 100 && phase === "in";
  useEffect(() => {
    if (!faded || !browserRunsAnimations()) return undefined;
    return schedule(() => setBar(NO_BAR), RESET_MS);
  }, [faded, schedule]);
  const barFaded = () => {
    if (faded) setBar(NO_BAR);
  };
  return { node: key === shown ? children : held.current, key: shown, phase, bar, barFaded };
}

/** A fade that the browser never runs (animations off, a hidden tab) must not leave the card or splash up, so the
 * hooks also remove them on the injected scheduler a little after the fade should have ended. Only where the
 * browser implements CSS animations at all (the DOM stand-ins used in unit tests do not, and have no fade to wait
 * for); the browser's own animationend normally comes first and cancels this. */
export const FADE_MARGIN_MS = 120;
export const SPLASH_FADE_MS = 450;
export const CARD_FADE_MS = 280;
export const browserRunsAnimations = (): boolean => typeof CSSAnimation !== "undefined";

/**
 * The card that is fading out: the loader's last step, kept on screen after the store has dropped it, until the
 * fade is over (`done`, from the browser's animationend, or the scheduler's fallback). Null when nothing is fading.
 */
export function useLeavingCard(
  wl: WorldLaunch | null,
  off: boolean,
): { leaving: WorldLaunch | null; done: () => void } {
  const schedule = useSchedule();
  const [prev, setPrev] = useState(wl);
  const [leaving, setLeaving] = useState<WorldLaunch | null>(null);
  if (wl !== prev) {
    setPrev(wl);
    if (wl !== null) {
      if (leaving !== null) setLeaving(null);
    } else if (prev !== null && prev.step >= 3 && !off) setLeaving(prev);
  }
  useEffect(() => {
    if (leaving === null || !browserRunsAnimations()) return undefined;
    return schedule(() => setLeaving(null), CARD_FADE_MS + FADE_MARGIN_MS);
  }, [leaving, schedule]);
  return { leaving: wl === null ? leaving : null, done: () => setLeaving(null) };
}
