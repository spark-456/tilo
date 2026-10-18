// Tilo W walk cycle constants and helpers (TW-2, PROMPT.md).
// Stride: 560 ms; speed: 130 px/s clamped to 0.6–3.4 s.

/** Stride duration in milliseconds (560 ms). */
export const WALK_STRIDE_MS = 560;

/** Walking speed in pixels per second (130 px/s). */
export const WALK_SPEED_PPS = 130;

/** Minimum travel duration in seconds (0.6 s). */
export const WALK_MIN_DURATION_S = 0.6;

/** Maximum travel duration in seconds (3.4 s). */
export const WALK_MAX_DURATION_S = 3.4;

/**
 * Computes travel duration in seconds for a given distance in pixels.
 * Under normal motion, clamped to 0.6–3.4 s.
 * Under reduced motion, returns 0.2 s (200 ms fade).
 */
export function walkDuration(distancePx: number, reducedMotion = false): number {
  if (reducedMotion) return 0.2;
  const raw = Math.abs(distancePx) / WALK_SPEED_PPS;
  return Math.min(WALK_MAX_DURATION_S, Math.max(WALK_MIN_DURATION_S, raw));
}

/**
 * Computes integer number of strides for a given duration in seconds.
 * Each stride is 0.56 s (560 ms). Clamped to at least 1 stride.
 */
export function walkStrides(durationSeconds: number): number {
  return Math.max(1, Math.round(durationSeconds / (WALK_STRIDE_MS / 1000)));
}

/** Small event-bound bob while an agent is walking; reduced motion keeps only the recorded slide. */
export const walkBob = (progress: number, reducedMotion: boolean): number =>
  reducedMotion ? 0 : Math.sin(Math.max(0, Math.min(1, progress)) * Math.PI * 8) * 1.35;
