// FR-UX-12 phone pass (f), BQ-WEB-MOTION-2b: one place that keeps the city pictures. A city is the world engine's
// one indivisible draw (an SVG of ~100 KB built as a string, about 150 ms at 4x CPU), so it is drawn once per
// (plan content, time of day) and handed back to every surface that wants it: the Worlds cards and the
// Spotlight, the World page, and the next visit to either. The key is the plan's content, not its object,
// because every Api call returns new objects; a plan object seen before skips even the key. The picture does not
// depend on its size (it fills its box), so size is not in the key. No animation is added: this is the same
// frozen picture, drawn earlier or not at all.
import type { Plan } from "../api/types";

type Draw<T> = (plan: Plan, night: boolean) => T;

/** The most pictures kept (a city is ~100 KB of SVG in a blob); the oldest goes first. */
const KEEP = 32;

const kept = new Map<string, unknown>();
const seen = new WeakMap<Plan, { day?: string; night?: string }>();

const keyOf = (plan: Plan, night: boolean): string => {
  const slot = night ? "night" : "day";
  let known = seen.get(plan);
  if (!known) {
    known = {};
    seen.set(plan, known);
  }
  known[slot] ??= `${slot}|${JSON.stringify(plan)}`;
  return known[slot];
};

/** The picture of `plan`: drawn by `draw` the first time, the same object afterwards. */
export function cachedCity<T>(plan: Plan, night: boolean, draw: Draw<T>): T {
  const key = keyOf(plan, night);
  if (kept.has(key)) return kept.get(key) as T;
  const picture = draw(plan, night);
  kept.set(key, picture);
  if (kept.size > KEEP) kept.delete(kept.keys().next().value as string);
  return picture;
}

/** Forget every picture (tests). */
export function clearCityCache(): void {
  kept.clear();
}
