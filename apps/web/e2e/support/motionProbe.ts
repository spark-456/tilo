// WEB-MOTION-2 test support: a probe that lives inside the page and writes down, from the first script on,
//   - every animation or transition the browser starts (CSS, WAAPI or script: whatever document.getAnimations() reports),
//     with its duration, easing, the properties it changes, the first and last value of each, and which part of the
//     app it is on (the boot splash, the page, the top progress bar, the world loader, the city);
//   - a sample every ~4 ms of the shell's chrome: the top bar (how visible, how full), the splash, the loader card
//     (how visible, how many steps are ticked, how full its bar), the page's text (to see when the page swaps), the
//     scroll position and the page's width.
// It polls with setInterval and never requestAnimationFrame, so it adds no frame to the app's own rAF count, and it
// never touches the page. The specs never ask HOW the app moves (CSS transition, CSS animation or script): they read
// what the browser says is running. Nothing here is bundled with the app.
import type { Page } from "@playwright/test";

export type Zone = "main" | "bar" | "splash" | "loader" | "city" | "other";

export interface AnimRec {
  /** ms since `start()` (or since the page began, before the first start()) when the probe NOTICED it: a busy main
   * thread notices late, so this is no measure of when the animation ran. */
  t: number;
  /** ms on the same clock when the animation itself began (its own startTime), which a busy main thread cannot
   * delay; falls back to `t` for an animation that was cancelled before it ever got a start time. */
  start: number;
  kind: "transition" | "animation" | "script";
  /** transitionProperty, animationName, or "" for script animations. */
  name: string;
  /** Properties the keyframes change (offset, easing and composite left out). */
  props: string[];
  dur: number;
  delay: number;
  iterations: number;
  /** The effect's own easing. */
  easing: string;
  /** The first keyframe's easing (CSS animations put their timing function there). */
  keyEasing: string;
  from: Record<string, string>;
  to: Record<string, string>;
  zone: Zone;
  tag: string;
  /** The element or one of its ancestors has a backdrop-filter. */
  blurred: boolean;
  /** The element itself has a backdrop-filter (an ancestor's does not count). */
  selfBlurred: boolean;
}

export interface Sample {
  t: number;
  /** The top progress bar's effective opacity (itself and every ancestor, visibility hidden counts as 0). */
  barOp: number;
  /** How much of the bar's track its fill covers, 0 to 1 (a scaleX, a width or a clipped slide all read the same). */
  barRatio: number;
  /** The nav is shown (not visibility: hidden). */
  navVisible: boolean;
  splash: { op: number } | null;
  loader: { op: number; ticks: number; ratio: number; rings: number } | null;
  /** Length and first 60 characters of <main>'s text: it changes when the page swaps. */
  mainText: string;
  path: string;
  scrollY: number;
  docW: number;
  clientW: number;
  /** Animations running right now outside the city. */
  running: number;
}

export interface ProbeData {
  recs: AnimRec[];
  samples: Sample[];
}

/** Runs inside the page (addInitScript): self-contained, no closure over this module. */
export function installProbe(): void {
  const w = window as unknown as { __probe?: unknown };
  if (w.__probe) return;
  const META = new Set(["offset", "easing", "composite", "computedOffset"]);
  const seen = new WeakSet<Animation>();
  const recs: AnimRec[] = [];
  /** Animations noticed before the browser gave them a startTime: read again until they have one. */
  const waiting: { rec: AnimRec; anim: Animation }[] = [];
  const samples: Sample[] = [];
  let t0 = 0;
  let baseline = -1;
  const now = (): number => performance.now() - t0;

  const zoneOf = (el: Element | null): Zone => {
    if (!el) return "other";
    if (el.closest(".park-shell__backdrop")) return "city";
    if (el.closest('[aria-label="Loading Tilo"]')) return "splash";
    if (el.closest(".park-shell__bar")) return "bar";
    const st = el.closest('[role="status"]');
    if (st && /OPENING/.test(st.textContent ?? "")) return "loader";
    if (el.closest("main")) return "main";
    return "other";
  };
  const effOp = (el: Element | null): number => {
    let op = 1;
    for (let n: Element | null = el; n; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.visibility === "hidden" && n === el) return 0;
      op *= Number(s.opacity);
    }
    return op;
  };
  const hasBlur = (n: Element): boolean => {
    const s = getComputedStyle(n);
    const wk = (s as unknown as Record<string, string>).webkitBackdropFilter ?? "none";
    return Boolean(s.backdropFilter && s.backdropFilter !== "none") || wk !== "none";
  };
  const blurredUp = (el: Element | null): boolean => {
    for (let n: Element | null = el; n && n !== document.documentElement; n = n.parentElement) {
      if (hasBlur(n)) return true;
    }
    return false;
  };
  /** The share of the track's width that the fill covers. */
  const ratio = (track: Element | null, fill: Element | null): number => {
    if (!track || !fill) return 0;
    const b = track.getBoundingClientRect();
    const f = fill.getBoundingClientRect();
    if (b.width <= 0) return 0;
    return Math.max(0, Math.min(f.right, b.right) - Math.max(f.left, b.left)) / b.width;
  };

  const record = (a: Animation): void => {
    const eff = a.effect as KeyframeEffect | null;
    if (!eff || typeof eff.getKeyframes !== "function") return;
    const target = eff.target as Element | null;
    const timing = eff.getTiming();
    const kfs = eff.getKeyframes();
    const props = new Set<string>();
    for (const k of kfs) for (const key of Object.keys(k)) if (!META.has(key)) props.add(key);
    const pick = (k: Keyframe | undefined): Record<string, string> => {
      const out: Record<string, string> = {};
      if (!k) return out;
      for (const key of props) {
        const v = (k as Record<string, unknown>)[key];
        if (v !== undefined && v !== null) out[key] = String(v);
      }
      return out;
    };
    const isTransition = typeof CSSTransition !== "undefined" && a instanceof CSSTransition;
    const isAnimation = typeof CSSAnimation !== "undefined" && a instanceof CSSAnimation;
    const rec: AnimRec = {
      t: now(),
      start: now(),
      kind: isTransition ? "transition" : isAnimation ? "animation" : "script",
      name: isTransition
        ? (a as CSSTransition).transitionProperty
        : isAnimation
          ? (a as CSSAnimation).animationName
          : "",
      props: [...props].sort(),
      dur: Number(timing.duration),
      delay: Number(timing.delay ?? 0),
      iterations: Number(timing.iterations ?? 1),
      easing: String(timing.easing ?? "linear"),
      keyEasing: String((kfs[0] as { easing?: string } | undefined)?.easing ?? "linear"),
      from: pick(kfs[0]),
      to: pick(kfs[kfs.length - 1]),
      zone: zoneOf(target),
      tag: target ? `${target.tagName.toLowerCase()}.${String(target.className).slice(0, 60)}` : "",
      blurred: blurredUp(target),
      selfBlurred: target ? hasBlur(target) : false,
    };
    recs.push(rec);
    if (a.startTime !== null) rec.start = Number(a.startTime) - t0;
    else waiting.push({ rec, anim: a });
  };

  const tick = (): void => {
    for (let i = waiting.length - 1; i >= 0; i--) {
      const w1 = waiting[i] as { rec: AnimRec; anim: Animation };
      if (w1.anim.startTime !== null) {
        w1.rec.start = Number(w1.anim.startTime) - t0;
        waiting.splice(i, 1);
      } else if (w1.anim.playState === "idle") waiting.splice(i, 1);
    }
    for (const a of document.getAnimations()) {
      if (seen.has(a)) continue;
      seen.add(a);
      record(a);
    }
    if (samples.length > 8000) return;
    const bar = document.querySelector(".park-shell__bar");
    const fill = bar?.firstElementChild ?? null;
    const sp = document.querySelector('[aria-label="Loading Tilo"]');
    const lo =
      [...document.querySelectorAll('[role="status"]')].find((e) =>
        /OPENING/.test(e.textContent ?? ""),
      ) ?? null;
    let loader: Sample["loader"] = null;
    if (lo) {
      const svgs = lo.querySelectorAll("svg").length;
      if (baseline < 0) baseline = svgs;
      const lbar = lo.querySelector(".park-shell__lbar");
      loader = {
        op: effOp(lo),
        ticks: svgs - baseline,
        ratio: ratio(lbar, lbar?.firstElementChild ?? null),
        rings: lo.querySelectorAll(".park-shell__ring").length,
      };
    } else baseline = -1;
    const header = document.querySelector("header");
    const main = document.querySelector("main");
    const text = main?.textContent ?? "";
    const de = document.documentElement;
    samples.push({
      t: now(),
      barOp: fill ? effOp(fill) : 0,
      barRatio: ratio(bar, fill),
      navVisible: !!header && getComputedStyle(header).visibility !== "hidden",
      splash: sp ? { op: effOp(sp) } : null,
      loader,
      mainText: `${text.length}|${text.slice(0, 60)}`,
      path: `${location.pathname}${location.search}`,
      scrollY: window.scrollY,
      docW: de.scrollWidth,
      clientW: de.clientWidth,
      running: document
        .getAnimations()
        .filter(
          (a) =>
            a.playState === "running" &&
            zoneOf(((a.effect as KeyframeEffect | null)?.target ?? null) as Element | null) !==
              "city",
        ).length,
    });
  };

  w.__probe = {
    /** Clears what was written and makes now() count from this moment. Animations already running are not re-recorded. */
    start(): void {
      recs.length = 0;
      samples.length = 0;
      waiting.length = 0;
      t0 = performance.now();
    },
    data(): ProbeData {
      return { recs: [...recs], samples: [...samples] };
    },
  };
  setInterval(tick, 4);
}

export const startProbe = (page: Page): Promise<void> =>
  page.evaluate(() => (window as unknown as { __probe: { start(): void } }).__probe.start());

export const readProbe = (page: Page): Promise<ProbeData> =>
  page.evaluate(() => (window as unknown as { __probe: { data(): ProbeData } }).__probe.data());
