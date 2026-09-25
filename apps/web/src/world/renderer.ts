// Draws a Frame (frame.ts) as placeholder shapes into the Pixi world container Stage.tsx owns:
// buildings/districts as flat iso diamonds, agents as dots. Art port is ticket P0-08c.
import { type Container, Graphics } from "pixi.js";
import tokens from "../design/tokens";
import type { Frame, FrameRect } from "./frame";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;
const AGENT_RADIUS = 6;

export interface WorldLayer {
  readonly buildings: Graphics;
  readonly agents: Graphics;
}

/** Appends this ticket's own two Graphics layers to `world` (after the camera's iso grid, which
 * is already `world`'s first child) — never touches the grid or the container's transform. */
export function createLayer(world: Container): WorldLayer {
  const buildings = new Graphics();
  const agents = new Graphics();
  world.addChild(buildings);
  world.addChild(agents);
  return { buildings, agents };
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
  layer.agents.clear();
  for (const agent of frame.agents) {
    const p = positions.get(agent.id);
    if (!p) continue;
    layer.agents.circle(p.x, p.y, AGENT_RADIUS).fill({ color: agent.color });
  }
}
