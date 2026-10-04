// Draws a Frame (frame.ts) into the Pixi world container Stage.tsx owns, with the art ported from
// the design prototypes (art/, ADR-0003): level plates, district plots, roads, bridges, buildings
// in their states, islands, gates, trees, agent figures, name tags and state pins, and (FR-WLD-06)
// a static outline ring round the selected object. Static things are one Graphics each, redrawn
// only when their own data changes; objects are depth-sorted by zIndex, so an agent walking behind
// a building is drawn behind it. Nothing here animates or decides when anything moves: positions
// come in already resolved by the choreographer's schedule (HR-3).
import { Container, Graphics } from "pixi.js";
import tokens from "../design/tokens";
import { AGENT_SCALE, drawAgent } from "./art/agent";
import { drawBuilding } from "./art/building";
import { hash } from "./art/color";
import {
  LEVEL_RISE,
  drawBridge,
  drawDistrict,
  drawGate,
  drawIsland,
  drawPlate,
  drawRoad,
  drawTree,
} from "./art/ground";
import { P } from "./art/iso";
import type { Pt } from "./art/iso";
import { buildingTag, districtTag, islandTag, policyTag } from "./art/labels";
import { type PinKind, drawPin } from "./art/pins";
import type { Frame, FrameRect } from "./frame";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;
const RING = { width: 3, color: tokens.color.brand.primary };

interface Item {
  readonly g: Graphics;
  key: string;
  top: readonly [number, number];
}

export interface WorldLayer {
  /** Holds everything below, offset and scaled once so the world sits framed in the stage. */
  readonly content: Container;
  readonly ground: Graphics;
  /** Buildings, islands, gates, trees and agents, depth-sorted by zIndex. */
  readonly objects: Container;
  readonly pins: Graphics;
  readonly labels: Container;
  /** The selection ring: redrawn only when the selection or the ringed thing's place changes. */
  readonly ring: Graphics;
  readonly items: Map<string, Item>;
  readonly figures: Map<string, { g: Graphics; key: string }>;
  readonly tags: Map<string, Container>;
  readonly size: () => { width: number; height: number };
  staticKey: string;
  groundKey: string;
  fitted: boolean;
}

/** Appends this layer to `world` (after the camera's iso grid, which is already its first child);
 * never touches the grid or the container's transform. `size` is the stage's pixel size. */
export function createLayer(world: Container, size: WorldLayer["size"]): WorldLayer {
  const content = new Container();
  const ground = new Graphics();
  const objects = new Container();
  objects.sortableChildren = true;
  const pins = new Graphics();
  const labels = new Container();
  const ring = new Graphics();
  content.addChild(ground, objects, pins, labels, ring);
  world.addChild(content);
  return {
    content,
    ground,
    objects,
    pins,
    labels,
    ring,
    items: new Map(),
    figures: new Map(),
    tags: new Map(),
    size,
    staticKey: "",
    groundKey: "",
    fitted: false,
  };
}

/** Frames the world once: centred on the stage, scaled down to fit but never below 0.5 (the
 * camera's own minimum) nor above 1. The camera stays the person's. */
function fit(layer: WorldLayer, b: Frame["bounds"]) {
  layer.fitted = true;
  const [bw, bh] = [b.x1 - b.x0, b.y1 - b.y0];
  if (bw <= 0 || bh <= 0) return;
  const { width, height } = layer.size();
  const s = Math.min(1, Math.max(0.5, Math.min((width * 0.92) / bw, (height * 0.92) / bh)));
  layer.content.scale.set(s);
  layer.content.position.set((-(b.x0 + b.x1) / 2) * s, (-(b.y0 + b.y1) / 2) * s);
}

/** Painter's order: what is nearer the viewer (larger gx + gy), and on a higher level, is later. */
const depth = (gx: number, gy: number, lift: number) => P(gx, gy)[1] + (lift / LEVEL_RISE) * 4000;

/** One static object's Graphics: created on first sight, redrawn only when `key` changes. `draw`
 * may set `it.top`, the point above the thing where its pin and tag hang. */
function item(
  layer: WorldLayer,
  id: string,
  key: string,
  z: number,
  draw: (g: Graphics, it: Item) => void,
): Item {
  let it = layer.items.get(id);
  if (!it) {
    it = { g: new Graphics(), key: "", top: [0, 0] };
    layer.objects.addChild(it.g);
    layer.items.set(id, it);
  }
  if (it.key !== key) {
    it.key = key;
    it.g.clear();
    draw(it.g, it);
  }
  it.g.zIndex = z;
  return it;
}

/** Shows the tag `id` at `at`, making it the first time; `live` collects what is shown. */
function tag(layer: WorldLayer, live: Set<string>, id: string, make: () => Container, at: Pt) {
  let t = layer.tags.get(id);
  if (!t) {
    t = make();
    layer.labels.addChild(t);
    layer.tags.set(id, t);
  }
  t.visible = true;
  t.position.set(at[0], at[1]);
  live.add(id);
}

const PIN: Readonly<Record<string, PinKind | undefined>> = {
  operational: "active",
  completed: "complete",
  archived: "skipped",
};
const GATE_PIN: Readonly<Record<string, PinKind>> = {
  closed: "lock",
  waiting: "needs",
  open: "complete",
  policy: "policy",
};

/** Static layer: plates, plots, roads, buildings, islands, gates, scenery, pins and tags, at their
 * authoritative frame positions. Each piece is redrawn only when its own data changed. */
export function renderStatic(layer: WorldLayer, frame: Frame) {
  if (!layer.fitted) fit(layer, frame.bounds);
  const groundKey = JSON.stringify([
    frame.plates,
    frame.districts.map((d) => [d.id, d.rect, d.tint]),
    frame.roads,
    frame.bridges,
  ]);
  const key = JSON.stringify([groundKey, frame.buildings, frame.islands, frame.gates]);
  if (key === layer.staticKey) return;
  layer.staticKey = key;

  if (groundKey !== layer.groundKey) {
    layer.groundKey = groundKey;
    const g = layer.ground.clear();
    for (const p of frame.plates) drawPlate(g, p.rect, p.lift);
    for (const d of frame.districts) drawDistrict(g, d.rect, d.tint, d.lift);
    for (const r of frame.roads) drawRoad(g, r.points, r.lift);
    for (const b of frame.bridges) drawBridge(g, b.points, b.kind, b.state, b.lift);
  }

  const seen = new Set<string>(); // items kept this frame; the rest are removed
  const live = new Set<string>(); // tags shown this frame
  const pinned: Array<() => void> = [];
  for (const p of frame.plates) {
    // Trees ring each plate on the margin: scenery, placed from the plate's id, so the same every time.
    const { x, y, w, d } = p.rect;
    const spots: Array<[number, number]> = [];
    for (let u = -0.45; u <= w + 0.45; u += 1.5)
      spots.push([x + u, y - 0.45], [x + u, y + d + 0.45]);
    for (let v = 1.05; v <= d - 1.05; v += 1.5)
      spots.push([x - 0.45, y + v], [x + w + 0.45, y + v]);
    for (const [gx, gy] of spots) {
      const h = hash(`${p.id}:${gx}:${gy}`);
      if (h % 10 >= 8) continue; // a gap now and then
      const id = `tree:${p.id}:${gx}:${gy}`;
      seen.add(id);
      item(layer, id, "t", depth(gx, gy, p.lift), (g) => {
        drawTree(g, gx, gy, 6 + (h % 4), h % 5 < 2);
        g.y = -p.lift;
      });
    }
  }
  for (const b of frame.buildings) {
    seen.add(b.id);
    const { x, y, w, d } = b.rect;
    const art = {
      ...b.rect,
      floors: b.floors,
      status: b.status,
      tint: b.tint,
      roof: b.roof,
      facade: b.facade,
      lift: b.lift,
    };
    const it = item(layer, b.id, JSON.stringify(b), depth(x + w / 2, y + d, b.lift), (g, self) => {
      self.top = drawBuilding(g, art);
    });
    const kind = PIN[b.status];
    if (kind) pinned.push(() => drawPin(layer.pins, it.top, kind, { tint: b.tint }));
    tag(layer, live, b.id, () => buildingTag(b.name), [it.top[0], it.top[1] - (kind ? 50 : 14)]);
  }
  for (const i of frame.islands) {
    seen.add(i.id);
    const { x, y, w, d } = i.rect;
    item(layer, i.id, JSON.stringify(i), depth(x + w / 2, y + d, i.lift), (g) =>
      drawIsland(g, i.rect, i.state, i.id, i.lift),
    );
    const [cx, cy] = P(x + w / 2, y + d / 2, i.lift);
    const pin = i.state === "locked" ? "lock" : i.state === "failed" ? "blocked" : null;
    if (pin) pinned.push(() => drawPin(layer.pins, [cx, cy + 18], pin, { lift: 0, r: 12 }));
    tag(layer, live, i.id, () => islandTag(i.name), [cx, cy + (pin ? 40 : 22)]);
  }
  for (const gt of frame.gates) {
    seen.add(gt.id);
    const [gx, gy] = P(gt.cell.x + 0.5, gt.cell.y + 0.5, gt.lift);
    item(layer, gt.id, JSON.stringify(gt), depth(gt.cell.x + 0.5, gt.cell.y + 0.9, gt.lift), (g) =>
      drawGate(g, gt.cell, gt.state, gt.lift),
    );
    pinned.push(() =>
      drawPin(layer.pins, [gx, gy - 22], GATE_PIN[gt.state] ?? "lock", { lift: 12, r: 9 }),
    );
    if (gt.state === "policy") tag(layer, live, `${gt.id}:policy`, policyTag, [gx, gy - 62]);
  }
  for (const d of frame.districts) {
    const [gx, gy] = P(d.rect.x + d.rect.w / 2, d.rect.y + d.rect.d, d.lift);
    tag(layer, live, d.id, () => districtTag(d.name, d.tint), [gx, gy + 16]);
  }
  layer.pins.clear();
  for (const draw of pinned) draw();
  for (const [id, it] of layer.items) {
    if (seen.has(id)) continue;
    it.g.destroy();
    layer.items.delete(id);
  }
  for (const [id, t] of layer.tags) t.visible = live.has(id);
}

/** Agents layer: one figure per spawned, placed agent, with its feet at `positions` (already
 * resolved/interpolated by the caller; this module draws, it never decides *when* something is at
 * a given position, which the choreographer alone owns, HR-3). */
export function renderAgents(
  layer: WorldLayer,
  frame: Frame,
  positions: ReadonlyMap<string, { x: number; y: number }>,
) {
  const shown = new Set<string>();
  for (const agent of frame.agents) {
    const p = positions.get(agent.id);
    if (!p) continue;
    const key = `${agent.rank}:${agent.tint}`;
    let fig = layer.figures.get(agent.id);
    if (!fig || fig.key !== key) {
      fig?.g.destroy();
      const g = new Graphics();
      drawAgent(g, agent.rank, agent.tint);
      g.scale.set(AGENT_SCALE);
      layer.objects.addChild(g);
      fig = { g, key };
      layer.figures.set(agent.id, fig);
    }
    fig.g.position.set(p.x, p.y);
    // In front of the building it stands at, behind one nearer the viewer.
    fig.g.zIndex = p.y + agent.level * LEVEL_RISE + agent.level * 4000 + 16;
    fig.g.visible = true;
    shown.add(agent.id);
  }
  for (const [id, fig] of layer.figures) if (!shown.has(id)) fig.g.visible = false;
}

/** FR-WLD-06: outlines the selected agent (an ellipse at its drawn place), building, district or
 * island (a diamond round its footprint); nothing is drawn for an id the stage has no shape for.
 * A selection is display state, so this never moves anything and never schedules a frame itself. */
export function renderSelection(
  layer: WorldLayer,
  frame: Frame,
  positions: ReadonlyMap<string, { x: number; y: number }>,
  id: string | null,
) {
  const g = layer.ring.clear();
  if (id === null) return;
  const at = frame.agents.some((a) => a.id === id) ? positions.get(id) : undefined;
  if (at) {
    g.ellipse(at.x, at.y, 22, 12.5).stroke(RING);
    return;
  }
  const r: FrameRect | undefined = [...frame.buildings, ...frame.districts, ...frame.islands].find(
    (x) => x.id === id,
  );
  if (!r) return;
  const hw = (r.gw * TW) / 2 + 4;
  const hd = (r.gd * TH) / 2 + 4;
  g.poly([r.cx, r.cy - hd, r.cx + hw, r.cy, r.cx, r.cy + hd, r.cx - hw, r.cy]).stroke(RING);
}
