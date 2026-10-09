// WEB_MOTION_1: fixed ticks, swept grid reservations, and no all-agent pair scan.
export interface Body {
  x: number;
  y: number;
  halfX: number;
  halfY: number;
}
export interface Route extends Body {
  kind: "car" | "walker";
  start: number;
  end: number;
  speed: number;
}
const TILE = 4;
export const TRAFFIC_TICK = 1 / 60;
class Grid {
  private cells = new Map<string, Set<number>>();
  private keys(p: Body): string[] {
    const keys: string[] = [];
    for (let x = Math.floor((p.x - p.halfX) / TILE); x <= Math.floor((p.x + p.halfX) / TILE); x++)
      for (let y = Math.floor((p.y - p.halfY) / TILE); y <= Math.floor((p.y + p.halfY) / TILE); y++)
        keys.push(`${x},${y}`);
    return keys;
  }
  add(p: Body, id: number): void {
    for (const key of this.keys(p)) {
      let ids = this.cells.get(key);
      if (!ids) {
        ids = new Set();
        this.cells.set(key, ids);
      }
      ids.add(id);
    }
  }
  free(p: Body, id: number): boolean {
    for (const key of this.keys(p))
      for (const other of this.cells.get(key) ?? []) if (other !== id) return false;
    return true;
  }
}
const swept = (a: Body, b: Body): Body => ({
  x: (a.x + b.x) / 2,
  y: (a.y + b.y) / 2,
  halfX: a.halfX + Math.abs(b.x - a.x) / 2,
  halfY: a.halfY + Math.abs(b.y - a.y) / 2,
});
export class CityTraffic {
  readonly positions: Route[];
  private routes: Route[];
  constructor(
    routes: readonly Route[],
    private standing: readonly Body[],
  ) {
    this.routes = routes.map((r) => ({ ...r }));
    this.positions = routes.map((r) => ({ ...r }));
    // Conservatively reserve footprints, including starting phases and standing agents.
    const grid = this.grid();
    this.positions.forEach((p, id) => {
      const dir = Math.sign(p.end - p.start);
      const original = p.x;
      for (let attempt = 0; !grid.free(p, id) && attempt < 1000; attempt++) {
        p.x = this.wrap(p.x + dir * TILE, p);
      }
      if (!grid.free(p, id)) throw new Error(`No free city spawn at ${original}`);
      grid.add(p, id);
    });
  }
  private grid(): Grid {
    const grid = new Grid();
    this.standing.forEach((p, i) => grid.add(p, -i - 1));
    return grid;
  }
  private wrap(x: number, r: Route): number {
    const dir = Math.sign(r.end - r.start);
    return dir * (x - r.end) > 0 ? r.start : x;
  }
  step(dt = TRAFFIC_TICK, loop = true, detour = true): void {
    const grid = this.grid();
    const people = this.grid();
    this.positions.forEach((p, id) => {
      grid.add(p, id);
      if (p.kind === "walker") people.add(p, id);
    });
    // Walkers reserve old AND new tiles before cars consider approaching them.
    for (const kind of ["walker", "car"] as const)
      this.positions.forEach((p, id) => {
        if (p.kind !== kind) return;
        const r = this.routes[id] as Route;
        const dir = Math.sign(r.end - r.start);
        let speed = r.speed;
        if (kind === "car") {
          const ahead = { ...p, x: p.x + dir * 24, halfX: p.halfX + 24 };
          if (!people.free(ahead, id)) speed = r.speed * 0.5;
          if (!people.free({ ...p, x: p.x + dir * 12, halfX: p.halfX + 12 }, id)) speed = 0;
        }
        const target = p.x + dir * speed * dt;
        const x = loop ? this.wrap(target, r) : dir * (target - r.end) > 0 ? r.end : target;
        const ys = kind === "walker" && detour ? [r.y, p.y, r.y - 20, r.y + 20] : [r.y];
        let moved = false;
        for (const y of ys) {
          const next = { ...p, x: y === p.y ? x : p.x, y };
          if (y === r.y && y !== p.y && !grid.free({ ...next, x: next.x + dir * 24 }, id)) continue;
          // A loop's endpoint teleports just as the original CSS loop did; all other travel is swept.
          const area = Math.abs(next.x - p.x) > r.speed ? next : swept(p, next);
          if (!grid.free(area, id)) continue;
          grid.add(area, id);
          if (kind === "walker") people.add(area, id);
          p.x = next.x;
          p.y = y;
          moved = true;
          break;
        }
        p.speed = moved ? speed : 0;
      });
  }
}

/** Independent lanes can shift clocks; interacting lanes retain their swept reservations. */
export function staggerTraffic(
  routes: readonly Route[],
  seed: number,
): { delay: number; edge: number }[] {
  const ordered = routes
    .map((r, id) => ({ id, lo: r.y - r.halfY, hi: r.y + r.halfY }))
    .sort((a, b) => a.lo - b.lo);
  const groups: number[][] = [];
  let hi = Number.NEGATIVE_INFINITY;
  for (const lane of ordered) {
    if (lane.lo > hi) groups.push([]);
    groups.at(-1)?.push(lane.id);
    hi = Math.max(hi, lane.hi);
  }
  const clocks = routes.map(() => ({ delay: 0, edge: 5 }));
  const rotation = ((seed >>> 0) % 997) / 997;
  groups.forEach((ids, i) => {
    // Fade windows stay disjoint even when the scene has many movers.
    const clock = {
      delay: -15 * ((i / groups.length + rotation) % 1),
      edge: Math.min(5, 40 / groups.length),
    };
    for (const id of ids) clocks[id] = clock;
  });
  return clocks;
}

// Sixty quarter-second segments. Lanes that can interact share the same clock;
// the final reset is discrete and hidden by each mover's opacity schedule.
export function compileTraffic(
  routes: readonly Route[],
  standing: readonly Body[],
  lanesOnly = false,
): Body[][] {
  const traffic = new CityTraffic(routes, standing);
  const frames = [traffic.positions.map((p) => ({ ...p }))];
  for (let i = 1; i < 60; i++) {
    traffic.step(0.25, false, !lanesOnly);
    frames.push(traffic.positions.map((p) => ({ ...p })));
  }
  return [...frames, frames[0] as Body[]];
}
