// Lanes for the city's ambient movers (FR-UX-12, issue #588). A car or a walker loops along one road, so two
// movers whose footprints overlap ACROSS the road will meet sooner or later, and so will a mover and an agent
// standing at the kerb. The only avoidance that needs no new keyframe is to give each its own lane: a lateral
// offset from the road's top edge. This is pure and deterministic (no randomness; ties go to the lower offset).

/** A strip across the road that something occupies: lateral offsets `lo` to `hi`. */
export interface Band {
  lo: number;
  hi: number;
}

/** Half-width of a car body and of a walking agent (13 x 1.1 scale), in road units (the scene's world px). */
export const CAR_HALF = 5.5;
export const WALKER_HALF = 7.15;
/** Half-width of an agent standing at a building, and where its centre sits below the road's top edge. */
export const STANDING_HALF = 7.475;
export const STANDING_AT = 3;
/** Clear space kept between two neighbours. */
const GAP = 0.5;
const STEP = 0.25;

/**
 * The offset (centre) nearest `pref` inside `range` whose strip of half-width `half` clears every taken band
 * by a gap, or null when none does.
 */
export function assignLane(
  pref: number,
  half: number,
  range: readonly [min: number, max: number],
  taken: readonly Band[],
): number | null {
  const [min, max] = range;
  const free = (c: number): boolean =>
    c >= min && c <= max && taken.every((t) => c + half + GAP <= t.lo || c - half - GAP >= t.hi);
  if (free(pref)) return pref;
  const n = Math.floor((max - min) / STEP);
  const all: number[] = [];
  for (let i = 0; i <= n; i++) all.push(min + i * STEP);
  all.sort((p, q) => Math.abs(p - pref) - Math.abs(q - pref) || p - q);
  return all.find(free) ?? null;
}

/** One thing in a road row, as reported to the caller (and to the test): its lane, or null when not drawn. */
export interface LaneRow {
  row: number;
  kind: "car" | "walker" | "standing";
  lane: number | null;
  pref: number;
  half: number;
}
