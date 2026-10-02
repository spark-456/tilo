// Draws a Frame (frame.ts) as placeholder shapes into the Pixi world container Stage.tsx owns:
// buildings/districts as flat iso diamonds, agents as dots, and (FR-WLD-06) a static outline ring
// round the selected object. Art port is ticket P0-08c.
import { Container, Graphics } from "pixi.js";
import tokens from "../design/tokens";
import type { Frame, FrameRect } from "./frame";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;
const AGENT_RADIUS = 6;

export interface WorldLayer {
  readonly buildings: Graphics;
  readonly agents: Container;
  /** The selection ring: redrawn only when the selection or the ringed thing's place changes. */
  readonly ring: Graphics;
  /** One persistent dot per agent id, filled once; each frame only moves it (no clear/refill). */
  readonly dots: Map<string, { g: Graphics; color: string }>;
  staticKey: string;
}

/** Appends this ticket's own two Graphics layers to `world` (after the camera's iso grid, which
 * is already `world`'s first child) — never touches the grid or the container's transform. */
export function createLayer(world: Container): WorldLayer {
  const buildings = new Graphics();
  const agents = new Container();
  const ring = new Graphics();
  world.addChild(buildings);
  world.addChild(agents);
  world.addChild(ring);
  return { buildings, agents, ring, dots: new Map(), staticKey: "" };
}

function diamond(g: Graphics, cx: number, cy: number, gw: number, gd: number, color: string) {
  const hw = (gw * TW) / 2;
  const hd = (gd * TH) / 2;
  g.poly([cx, cy - hd, cx + hw, cy, cx, cy + hd, cx - hw, cy]).fill({ color });
}

function drawRects(g: Graphics, rects: readonly FrameRect[]) {
  for (const r of rects) diamond(g, r.cx, r.cy, r.gw, r.gd, r.color);
}

/** Static layer: districts and buildings, at their authoritative frame positions. Redrawn only
 * when the applied event actually changed something (not every animation tick). */
export function renderStatic(layer: WorldLayer, frame: Frame) {
  const key = JSON.stringify([frame.districts, frame.buildings]);
  if (key === layer.staticKey) return;
  layer.staticKey = key;
  layer.buildings.clear();
  drawRects(layer.buildings, frame.districts);
  drawRects(layer.buildings, frame.buildings);
}

/** Agents layer: one dot per spawned, placed agent, at `positions` (already resolved/interpolated
 * by the caller — this module draws, it never decides *when* something is at a given position;
 * the choreographer alone owns that, per HR-3). */
export function renderAgents(
  layer: WorldLayer,
  frame: Frame,
  positions: ReadonlyMap<string, { x: number; y: number }>,
) {
  const shown = new Set<string>();
  let added = false;
  for (const agent of frame.agents) {
    const p = positions.get(agent.id);
    if (!p) continue;
    let dot = layer.dots.get(agent.id);
    if (!dot || dot.color !== agent.color) {
      dot?.g.destroy();
      const g = new Graphics().circle(0, 0, AGENT_RADIUS).fill({ color: agent.color });
      layer.agents.addChild(g);
      added = true;
      dot = { g, color: agent.color };
      layer.dots.set(agent.id, dot);
    }
    dot.g.position.set(p.x, p.y);
    dot.g.visible = true;
    shown.add(agent.id);
  }
  for (const [id, dot] of layer.dots) if (!shown.has(id)) dot.g.visible = false;
  // Keep draw order = frame order however the dots were revealed, so overlaps match ?seq=N.
  if (added) {
    let i = 0;
    for (const agent of frame.agents) {
      const dot = layer.dots.get(agent.id);
      if (dot) layer.agents.setChildIndex(dot.g, i++);
    }
  }
}

/** FR-WLD-06: outlines the selected agent (a circle at its drawn place), building or district (a
 * diamond round its footprint); nothing is drawn for an id the stage has no shape for. A selection
 * is display state, so this never moves anything and never schedules a frame itself. */
export function renderSelection(
  layer: WorldLayer,
  frame: Frame,
  positions: ReadonlyMap<string, { x: number; y: number }>,
  id: string | null,
) {
  const g = layer.ring.clear();
  if (id === null) return;
  const stroke = { width: 3, color: tokens.color.brand.primary };
  const at = frame.agents.some((a) => a.id === id) ? positions.get(id) : undefined;
  if (at) {
    g.circle(at.x, at.y, AGENT_RADIUS + 5).stroke(stroke);
    return;
  }
  const r = [...frame.buildings, ...frame.districts].find((x) => x.id === id);
  if (!r) return;
  const hw = (r.gw * TW) / 2 + 4;
  const hd = (r.gd * TH) / 2 + 4;
  g.poly([r.cx, r.cy - hd, r.cx + hw, r.cy, r.cx, r.cy + hd, r.cx - hw, r.cy]).stroke(stroke);
}
