// HR-6 replay speed: the one place `?speed=` is read and worded, for the stage fixture player and
// the fixture client alike (issue #43: ?speed=1e308 gave a broken badge and a runaway replay).

/** The slowest and fastest replay either player runs at; anything outside is clamped. */
export const MIN_SPEED = 0.1;
export const MAX_SPEED = 1000;

/** A `?speed=` value as a replay speed: no value, zero, a negative or text means 1 (the recorded
 * pace); anything else is clamped to MIN_SPEED..MAX_SPEED and rounded to two decimals, so the
 * badge shows exactly what plays. */
export function parseSpeed(raw: string | null): number {
  if (raw === null) return 1;
  const n = Number(raw);
  if (Number.isNaN(n) || n <= 0) return 1;
  return Math.round(Math.min(MAX_SPEED, Math.max(MIN_SPEED, n)) * 100) / 100;
}

/** The HR-6 badge text, in words ("Replay at 20× speed"), or null at the recorded pace. */
export const speedBadgeText = (speed: number): string | null =>
  speed === 1 ? null : `Replay at ${speed}× speed`;
