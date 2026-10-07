// The shell's chrome motion, driven by state (WEB-MOTION-2; README "Interactions and motion": Page change, Open a
// world, Boot; PRD 9.4: it moves only because a person acted, never because of an agent). Three hooks, no timer of
// their own: the page swap waits on the provider's injected scheduler, and the two fades (the boot splash, the world
// card) wait for the browser's own animationend. The CSS that moves things is park.shell.css; this file only decides
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
const IN_MS = 40;
const HIDE_MS = 420;
const RESET_MS = 360;

export interface PageSwap {
  /** What the page outlet draws: the page the person left while it fades out, else the live page. */
  node: ReactNode;
  /** The key of the page on screen. */
  key: string;
  /** "in" is the settled state; "out", "pre" and "hold" are the stages of a swap (a data attribute on <main>). */
  phase: Phase;
  bar: Bar;
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
      return schedule(() => {
        startTransition(() => {
          setShown(latest.current);
          setPhase("pre");
          setBar({ on: true, pct: 78 });
        });
      }, OUT_MS);
    }
    if (phase === "pre") {
      return schedule(() => {
        setPhase("in");
        setBar({ on: true, pct: 100 });
      }, IN_MS);
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
  // In the commit that puts the new page on screen, so the scroll and the swap are one step.
  useLayoutEffect(() => {
    if (phase === "pre") window.scrollTo(0, 0);
  }, [phase]);
  useEffect(() => {
    if (phase !== "in" || bar.pct !== 100) return undefined;
    return schedule(
      () => setBar(bar.on ? { on: false, pct: 100 } : NO_BAR),
      bar.on ? HIDE_MS : RESET_MS,
    );
  }, [phase, bar, schedule]);
  return { node: key === shown ? children : held.current, key: shown, phase, bar };
}

/**
 * The card that is fading out: the loader's last step, kept on screen after the store has dropped it, until the
 * fade is over (`done`, from the browser's animationend). Null when nothing is fading.
 */
export function useLeavingCard(
  wl: WorldLaunch | null,
  off: boolean,
): { leaving: WorldLaunch | null; done: () => void } {
  const [prev, setPrev] = useState(wl);
  const [leaving, setLeaving] = useState<WorldLaunch | null>(null);
  if (wl !== prev) {
    setPrev(wl);
    if (wl !== null) {
      if (leaving !== null) setLeaving(null);
    } else if (prev !== null && prev.step >= 3 && !off) setLeaving(prev);
  }
  return { leaving: wl === null ? leaving : null, done: () => setLeaving(null) };
}
