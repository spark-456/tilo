// TILO-T-WORLD: replay stepping for a finished world (design/tilo-t PROMPT.md section 3, "Playback"): Pause, 1x, 2x
// and Catch up step through the recorded events at 2200, 1100 and 260 ms per event. It only moves the world's replay
// point (display state, HR-4); every change the stage shows is still the recorded event at that point.
export type Speed = "paused" | "1x" | "2x" | "catch";

export const STEP_MS: Readonly<Record<Exclude<Speed, "paused">, number>> = {
  "1x": 2200,
  "2x": 1100,
  catch: 260,
};

/** What follows a step: the next stop while the run has more, else the replay rests (Catch up falls back to 1x). */
export function afterStep(
  speed: Speed,
  index: number,
  last: number,
): { index: number; speed: Speed } {
  if (speed === "paused") return { index, speed };
  if (index >= last) return { index: last, speed: speed === "catch" ? "1x" : "paused" };
  return { index: index + 1, speed };
}
