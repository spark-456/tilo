// Tilo T motion constants (design/tilo-t/PROMPT.md section 2; the same values are the CSS custom properties in motion.css).
// Honesty rule (PRD 9.4): every work animation is driven by a recorded agent event. A component that starts one names that
// event beside the start: `triggeredBy: "building.constructing"`, or a comment saying so. Ambient decoration is the only
// exception (clouds, doodles, idle blinks, loading shimmer).

/** The three easing tokens. standard: things appearing, panels, the camera. walk: agents and parcels. leap: the pool loader jump. */
export const EASING = {
  standard: "cubic-bezier(.2,.8,.2,1)",
  walk: "cubic-bezier(.45,0,.2,1)",
  leap: "cubic-bezier(.5,0,.5,1)",
} as const;

export type EasingName = keyof typeof EASING;

/** The CSS custom property that carries each easing (defined on :root in motion.css). */
export const EASING_VAR = {
  standard: "var(--tt-ease-standard)",
  walk: "var(--tt-ease-walk)",
  leap: "var(--tt-ease-leap)",
} as const;

/** Reduced motion: every walk, rise and flight becomes a fade of this length in ms (the design allows 200 to 300). */
export const REDUCED_FADE_MS = 250;

/** True when the person asked the system for less motion. Components that run a timed JS step read this; CSS uses the media query. */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}
