// Draws a Frame (frame.ts) as placeholder shapes into the Pixi world container Stage.tsx owns:
// buildings/districts as flat iso diamonds, agents as dots. Art port is ticket P0-08c.
import { Container, Graphics } from "pixi.js";
import tokens from "../design/tokens";
import type { Frame, FrameRect } from "./frame";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;
const AGENT_RADIUS = 6;

export interface WorldLayer {
  readonly buildings: Graphics;
  readonly agents: Container;
  /** One persistent dot per agent id, filled once; each frame only moves it (no clear/refill). */
  readonly dots: Map<string, { g: Graphics; color: string }>;
  staticKey: string;
}

/** Appends this ticket's own two Graphics layers to `world` (after the camera's iso grid, which
 * is already `world`'s first child) — never touches the grid or the container's transform. */
export function createLayer(world: Container): WorldLayer {
  const buildings = new Graphics();
  const agents = new Container();
  world.addChild(buildings);
  world.addChild(agents);
  return { buildings, agents, dots: new Map(), staticKey: "" };
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
