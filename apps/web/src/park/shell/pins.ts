// THROWAWAY (WEB-3b validation only).
import type { Spot } from "../engines/types";

export function scenePins(
  spots: readonly Spot[],
  vw: number,
  vh: number,
): { x: number; y: number }[] {
  const scale = Math.max(vw / 1600, vh / 1000);
  const used = new Set<number>();
  const near = (t: [number, number], min: number): { x: number; y: number } => {
    let best = -1;
    let bd = 1e9;
    spots.forEach((p, i) => {
      if (used.has(i) || p.area < min) return;
      const d = Math.hypot(p.x - t[0], p.y - t[1]);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    const hit = spots[best];
    if (!hit) return { x: t[0], y: t[1] };
    used.add(best);
    return hit;
  };
  const raw = [near([1000, 420], 4), near([820, 640], 4), near([900, 250], 2)];
  return raw.map((p) => ({ x: (p.x - 800) * scale + vw / 2, y: (p.y - 500) * scale + vh / 2 }));
}
